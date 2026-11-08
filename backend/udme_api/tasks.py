from celery import shared_task
from django.db import transaction
from udme_core.model import Package
from udme_core.pipeline import analyze
from . import models as M

HUMAN_REL = ("accepted", "rejected", "investigate", "conflict")
HUMAN_MAP = ("approved", "edited", "rejected")


def _rkey(d): return (d["source_table"], tuple(d["source_columns"]), d["target_table"], tuple(d["target_columns"]))


def carry_decisions(scan, rels: list, maps: list) -> dict:
    """Re-apply the previous scan's human decisions on the same site.
    - decided relations present again keep their decision;
    - an ACCEPTED relation that vanished is never silently dropped: it becomes a 'conflict' needing review;
    - approved/edited labels are kept; a rejected label stays rejected only if the same label is proposed again."""
    prev = (M.ScanPackage.objects.filter(site=scan.site, created_at__lt=scan.created_at).exclude(status="failed")
            .order_by("-created_at").first())
    stats = {"carried": 0, "conflicts": 0, "from": None}
    if not prev: return stats
    stats["from"] = str(prev.pk); by_key = {_rkey(r.data): r for r in rels}; extra = []
    for old in prev.relationships.filter(status__in=HUMAN_REL):
        if old.data.get("declared"): continue
        cur = by_key.get(_rkey(old.data))
        if cur is not None and old.status != "conflict":
            cur.status = old.status; cur.data = {**cur.data, "status": old.status, "carried_from": str(prev.pk)}; stats["carried"] += 1
        elif cur is None and old.status in ("accepted", "conflict"):
            d = {**old.data, "status": "conflict", "evidence": list(dict.fromkeys(old.data["evidence"] + ["missing_in_new_scan"])), "carried_from": str(prev.pk)}
            extra.append(M.RelationshipCandidate(tenant=scan.tenant, scan=scan, data=d, score=old.score, status="conflict")); stats["conflicts"] += 1
    rels.extend(extra)
    prev_maps = {b.object_id: b for b in prev.mappings.filter(status__in=HUMAN_MAP)}
    for b in maps:
        o = prev_maps.get(b.object_id)
        if not o: continue
        if o.status in ("approved", "edited"):
            b.label, b.status = o.label, o.status; b.evidence = list(b.evidence) + [f"carried_from_scan:{prev.pk}"]; stats["carried"] += 1
        elif o.status == "rejected" and b.label == o.label:
            b.status = "rejected"; stats["carried"] += 1
    return stats


@shared_task
def analyze_scan(scan_pk: str):
    scan = M.ScanPackage.objects.select_related("tenant", "site").get(pk=scan_pk)
    try:
        res = analyze(Package.model_validate(scan.package))
        rels = [M.RelationshipCandidate(tenant=scan.tenant, scan=scan, data=r.model_dump(), score=r.score,
                status="accepted" if r.declared else "needs_review") for r in res.relationships]
        maps = [M.BusinessMapping(tenant=scan.tenant, scan=scan, object_id=b.object_id, label=b.label, confidence=b.confidence,
                evidence=b.evidence, alternatives=b.alternatives) for b in res.mappings]
        with transaction.atomic():
            stats = carry_decisions(scan, rels, maps)
            M.RelationshipCandidate.objects.bulk_create(rels); M.BusinessMapping.objects.bulk_create(maps)
            scan.schema_hash = res.schema_hash; scan.status = "review_required"; scan.save(update_fields=["schema_hash", "status"])
            M.AuditEvent.objects.create(tenant=scan.tenant, actor="system", action="scan.decisions_carried", resource=str(scan.pk), details=stats)
    except Exception:
        scan.status = "failed"; scan.save(update_fields=["status"]); raise

from celery import shared_task
from django.db import transaction
from udme_core.model import Package
from udme_core.pipeline import analyze
from . import models as M


@shared_task
def analyze_scan(scan_pk: str):
    scan = M.ScanPackage.objects.get(pk=scan_pk)
    try:
        res = analyze(Package.model_validate(scan.package))
        with transaction.atomic():
            M.RelationshipCandidate.objects.bulk_create([M.RelationshipCandidate(
                tenant=scan.tenant, scan=scan, data=r.model_dump(), score=r.score,
                status="accepted" if r.declared else "needs_review") for r in res.relationships])
            M.BusinessMapping.objects.bulk_create([M.BusinessMapping(
                tenant=scan.tenant, scan=scan, object_id=b.object_id, label=b.label, confidence=b.confidence,
                evidence=b.evidence, alternatives=b.alternatives) for b in res.mappings])
            scan.schema_hash = res.schema_hash; scan.status = "review_required"
            scan.save(update_fields=["schema_hash", "status"])
    except Exception:
        scan.status = "failed"; scan.save(update_fields=["status"]); raise

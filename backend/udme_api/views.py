import hmac
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, NotFound, AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.authentication import BaseAuthentication
from udme_core.package import verify_envelope
from udme_core.model import Package
from udme_core.pipeline import analyze, diff as pkg_diff
from udme_core import exporters as ex
import secrets
from . import models as M
from .tasks import analyze_scan


def audit(tenant, actor, action, resource="", **details):
    M.AuditEvent.objects.create(tenant=tenant, actor=str(actor), action=action, resource=str(resource), details=details)


class AgentAuth(BaseAuthentication):
    """Authorization: Agent <agent_id>:<secret>. Narrow device scope; revoked agents are refused."""
    def authenticate(self, request):
        h = request.headers.get("Authorization", "")
        if not h.startswith("Agent "): return None
        try:
            aid, sec = h[6:].split(":", 1); a = M.Agent.objects.select_related("tenant").get(pk=aid)
        except Exception:
            raise AuthenticationFailed("invalid agent credential")
        if a.revoked or not hmac.compare_digest(a.secret, sec): raise AuthenticationFailed("invalid agent credential")
        return (None, a)
    def authenticate_header(self, request): return "Agent"


def membership(request, roles=None):
    m = M.Membership.objects.filter(user=request.user).select_related("tenant").first()
    if not m or (roles and m.role not in roles): raise PermissionDenied("TENANT_SCOPE_VIOLATION")
    return m


def own_scan(request, pk, roles=None):
    m = membership(request, roles)
    try: return M.ScanPackage.objects.get(pk=pk, tenant=m.tenant), m  # tenant-scoped lookup
    except M.ScanPackage.DoesNotExist: raise NotFound()


class EnrollmentTokenView(APIView):
    def post(self, request, site_id):
        m = membership(request, {"admin"})
        site = M.Site.objects.filter(pk=site_id, tenant=m.tenant).first() or (_ for _ in ()).throw(NotFound())
        raw = M.EnrollmentToken.issue(site); audit(m.tenant, request.user.pk, "enrollment_token.issued", site.pk)
        return Response({"token": raw, "expires_in_minutes": 30}, status=201)


class AgentEnrollView(APIView):
    authentication_classes = []; permission_classes = [AllowAny]
    @transaction.atomic
    def post(self, request):
        tok = M.EnrollmentToken.consume(str(request.data.get("token", "")))
        if not tok: return Response({"code": "ENROLLMENT_TOKEN_INVALID"}, status=403)
        secret = secrets.token_urlsafe(32)
        a = M.Agent.objects.create(tenant=tok.tenant, site=tok.site, name=request.data.get("name", ""), secret=secret)
        audit(tok.tenant, a.pk, "agent.enrolled", a.pk)
        return Response({"agent_id": str(a.pk), "tenant_id": str(tok.tenant_id), "secret": secret}, status=201)  # shown once


class AgentRevokeView(APIView):
    def post(self, request, agent_id):
        m = membership(request, {"admin"})
        n = M.Agent.objects.filter(pk=agent_id, tenant=m.tenant).update(revoked=True)
        if not n: raise NotFound()
        audit(m.tenant, request.user.pk, "agent.revoked", agent_id); return Response(status=204)


class IngestView(APIView):
    authentication_classes = [AgentAuth]; permission_classes = [AllowAny]
    def post(self, request):
        agent = request.auth
        if not isinstance(agent, M.Agent): raise AuthenticationFailed()
        env = request.data
        if str(env.get("tenant_id")) != str(agent.tenant_id) or str(env.get("agent_id")) != str(agent.pk):
            audit(agent.tenant, agent.pk, "ingest.tenant_scope_violation")
            return Response({"code": "TENANT_SCOPE_VIOLATION"}, status=403)
        try:
            pkg = verify_envelope(dict(env), agent.secret)
        except Exception as e:
            audit(agent.tenant, agent.pk, "ingest.rejected", reason=str(e))
            return Response({"code": "PACKAGE_INVALID", "reason": str(e)}, status=400)
        existing = M.ScanPackage.objects.filter(agent=agent, scan_id=env["scan_id"]).first()
        if existing: return Response({"scan_id": str(existing.pk), "status": existing.status}, status=200)  # idempotent retry
        try:
            sp = M.ScanPackage.objects.create(tenant=agent.tenant, site=agent.site, agent=agent, scan_id=env["scan_id"],
                  nonce=env["nonce"], checksum=env["checksum"], engine=pkg.source.engine,
                  engine_version=pkg.source.engine_version or "", package=pkg.model_dump(mode="json"))
        except IntegrityError:
            return Response({"code": "PACKAGE_INVALID", "reason": "replayed_nonce"}, status=409)
        agent.last_seen_at = timezone.now(); agent.save(update_fields=["last_seen_at"])
        audit(agent.tenant, agent.pk, "scan.uploaded", sp.pk)
        analyze_scan.delay(str(sp.pk))
        return Response({"scan_id": str(sp.pk), "status_url": f"/api/v1/scans/{sp.pk}"}, status=202)


class ScanListView(APIView):
    def get(self, request):
        m = membership(request)
        qs = M.ScanPackage.objects.filter(tenant=m.tenant).order_by("-created_at")[:100]
        return Response([{"id": s.pk, "site": s.site.name, "engine": s.engine, "status": s.status,
                          "schema_hash": s.schema_hash, "created_at": s.created_at} for s in qs])


class ScanDetailView(APIView):
    def get(self, request, pk):
        s, _ = own_scan(request, pk); p = s.package
        tables = [{"schema": sc["name"], "name": t["name"], "type": t["object_type"], "columns": len(t["columns"])}
                  for sc in p["schemas"] for t in sc["tables"]]
        return Response({"id": s.pk, "status": s.status, "engine": s.engine, "engine_version": s.engine_version,
                         "warnings": p["source"]["warnings"], "metadata_only": p["source"]["metadata_only"],
                         "objects": tables, "pending_reviews": s.relationships.filter(status="needs_review").count()
                         + s.mappings.filter(status="needs_review").count()})


class GraphView(APIView):
    def get(self, request, pk):
        s, _ = own_scan(request, pk); min_score = float(request.query_params.get("min_score", 0))
        edges = [{"id": r.pk, **r.data, "status": r.status} for r in s.relationships.filter(score__gte=min_score)]
        labels = {b.object_id: {"mapping_id": b.pk, "evidence": b.evidence, "alternatives": b.alternatives, "label": b.label, "confidence": b.confidence, "status": b.status} for b in s.mappings.all()}
        nodes = [{"id": f"{sc['name']}.{t['name']}", **labels.get(f"{sc['name']}.{t['name']}", {})}
                 for sc in s.package["schemas"] for t in sc["tables"]]
        return Response({"nodes": nodes, "edges": edges})


class ReviewView(APIView):
    kind = None
    def post(self, request, pk):
        m = membership(request, {"admin", "reviewer"})
        Model = M.RelationshipCandidate if self.kind == "relationship" else M.BusinessMapping
        obj = Model.objects.filter(pk=pk, tenant=m.tenant).first() or (_ for _ in ()).throw(NotFound())
        decision = request.data.get("decision")
        allowed = {"accept", "reject", "investigate", "edit"} if self.kind == "mapping" else {"accept", "reject", "investigate"}
        if decision not in allowed: return Response({"code": "INVALID_DECISION"}, status=400)
        prev = obj.status
        if self.kind == "mapping" and decision == "edit":
            obj.label = request.data.get("label") or (_ for _ in ()).throw(PermissionDenied("label required"))
        obj.status = {"accept": "accepted" if self.kind == "relationship" else "approved", "reject": "rejected",
                      "investigate": "investigate", "edit": "edited"}[decision]
        obj.save()
        M.MappingReview.objects.create(tenant=m.tenant, target_type=self.kind, target_id=obj.pk, reviewer=request.user,
                                       previous=prev, decision=decision, new_label=obj.label if self.kind == "mapping" else "",
                                       comment=request.data.get("comment", ""))
        audit(m.tenant, request.user.pk, f"{self.kind}.reviewed", obj.pk, decision=decision)
        return Response({"id": obj.pk, "status": obj.status})


class ExportView(APIView):
    def get(self, request, pk):
        s, m = own_scan(request, pk); fmt = request.query_params.get("fmt", "json")
        pkg = Package.model_validate(s.package); res = analyze(pkg)
        rels = [r for r in res.relationships]
        rejected = {(x.data["source_table"], tuple(x.data["source_columns"]), x.data["target_table"]) for x in s.relationships.filter(status="rejected")}
        rels = [r for r in rels if (r.source_table, tuple(r.source_columns), r.target_table) not in rejected]  # honour human decisions
        for x in s.relationships.filter(status="accepted"):
            for r in rels:
                if r.source_table == x.data["source_table"] and r.source_columns == x.data["source_columns"] and r.target_table == x.data["target_table"]:
                    r.status = "accepted"
        maps = res.mappings
        out = {"json": (ex.to_json(pkg, rels, maps), "application/json"), "csv": (ex.relationships_csv(rels), "text/csv"),
               "md": (ex.to_markdown(pkg, rels, maps), "text/markdown"), "ddl": (ex.to_ddl(pkg), "text/plain")}.get(fmt)
        if not out: return Response({"code": "UNSUPPORTED_FORMAT"}, status=400)
        audit(m.tenant, request.user.pk, "export.created", s.pk, format=fmt)
        return HttpResponse(out[0], content_type=out[1])


class DiffView(APIView):
    def get(self, request, pk, base_pk):
        a, _ = own_scan(request, pk); b, _ = own_scan(request, base_pk)
        return Response(pkg_diff(Package.model_validate(b.package), Package.model_validate(a.package)))


class TablesView(APIView):
    """Full column detail for the schema explorer."""
    def get(self, request, pk):
        s, _ = own_scan(request, pk)
        return Response([{"id": f"{sc['name']}.{t['name']}", "type": t["object_type"], "columns": t["columns"],
                         "primary_key": t["primary_key"], "foreign_keys": t["foreign_keys"], "indexes": t["indexes"]}
                         for sc in s.package["schemas"] for t in sc["tables"]])


class MeView(APIView):
    def get(self, request):
        m = membership(request)
        return Response({"user": request.user.username, "tenant": m.tenant.name, "role": m.role})


class HealthView(APIView):
    authentication_classes = []; permission_classes = [AllowAny]; throttle_classes = []
    def get(self, request):
        from django.db import connection
        connection.ensure_connection(); return Response({"status": "ok"})


class SitesView(APIView):
    def get(self, request):
        m = membership(request)
        return Response([{"id": s.pk, "name": s.name, "agents": s.agent_set.filter(revoked=False).count()} for s in M.Site.objects.filter(tenant=m.tenant)])


def spa(request, path=""):
    """Angular client-side routes: always return index.html (real files are served by WhiteNoise first)."""
    from django.conf import settings
    try: return HttpResponse(open(settings.FRONTEND_INDEX, "rb").read(), content_type="text/html")
    except OSError: return HttpResponse("UDME API is running (frontend not built).", status=200)

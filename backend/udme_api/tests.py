import json, sqlite3, tempfile, os, sys
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from django.test import TestCase
from udme_core.connectors import SQLAlchemyConnector
from udme_core.package import sign_envelope
from . import models as M
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
from make_fixture import build


def make_tenant(name):
    t = M.Tenant.objects.create(name=name); u = User.objects.create_user(name, password="x")
    M.Membership.objects.create(tenant=t, user=u, role="admin"); s = M.Site.objects.create(tenant=t, name="Site")
    c = APIClient(); c.force_authenticate(u); return t, u, s, c


class Flow(TestCase):
    def setUp(self):
        self.t, self.u, self.site, self.c = make_tenant("A")
        d = tempfile.mkdtemp(); p = os.path.join(d, "x.db"); build(p)
        con = SQLAlchemyConnector(f"sqlite:///{p}"); self.pkg = con.extract("WinGest"); con.close()
        tok = self.c.post(f"/api/v1/sites/{self.site.pk}/enrollment-tokens").json()["token"]
        self.tok = tok; self.ag = APIClient().post("/api/v1/agents/enroll", {"token": tok}, format="json").json()

    def upload(self, **kw):
        env = sign_envelope(self.pkg, tenant_id=self.ag["tenant_id"], agent_id=self.ag["agent_id"],
                            scan_id=kw.pop("scan_id", "11111111-1111-1111-1111-111111111111"), secret=kw.pop("secret", self.ag["secret"]))
        env.update(kw); a = APIClient()
        return a.post("/api/v1/scans/ingest", env, format="json", HTTP_AUTHORIZATION=f"Agent {self.ag['agent_id']}:{self.ag['secret']}")

    def test_full_flow(self):
        r = self.upload(); self.assertEqual(r.status_code, 202)
        sid = r.json()["scan_id"]
        d = self.c.get(f"/api/v1/scans/{sid}").json()
        self.assertEqual(d["status"], "review_required"); self.assertTrue(d["metadata_only"])
        g = self.c.get(f"/api/v1/scans/{sid}/graph").json(); self.assertGreaterEqual(len(g["edges"]), 5)
        edge = next(e for e in g["edges"] if e["status"] == "needs_review")
        self.assertEqual(self.c.post(f"/api/v1/relationships/{edge['id']}/review", {"decision": "reject"}, format="json").status_code, 200)
        csv = self.c.get(f"/api/v1/scans/{sid}/export?fmt=csv").content.decode()
        self.assertNotIn(f"{edge['source_table']},{','.join(edge['source_columns'])},{edge['target_table']}", csv.replace("\r", ""))
        self.assertEqual(self.c.get(f"/api/v1/scans/{sid}/export?fmt=md").status_code, 200)
        self.assertTrue(M.AuditEvent.objects.filter(action="relationship.reviewed").exists())
        self.assertEqual(self.upload().status_code, 200)  # same scan_id => idempotent retry, no duplicate
        self.assertEqual(M.ScanPackage.objects.count(), 1)

    def test_enrollment_token_single_use(self):
        r = APIClient().post("/api/v1/agents/enroll", {"token": self.tok}, format="json"); self.assertEqual(r.status_code, 403)

    def test_bad_signature_and_replay(self):
        self.assertEqual(self.upload(secret="wrong").status_code, 400)
        env = sign_envelope(self.pkg, tenant_id=self.ag["tenant_id"], agent_id=self.ag["agent_id"], scan_id="22222222-2222-2222-2222-222222222222", secret=self.ag["secret"])
        a = APIClient(); h = {"HTTP_AUTHORIZATION": f"Agent {self.ag['agent_id']}:{self.ag['secret']}"}
        self.assertEqual(a.post("/api/v1/scans/ingest", env, format="json", **h).status_code, 202)
        env["scan_id"] = "33333333-3333-3333-3333-333333333333"  # tampered after signing => rejected
        self.assertEqual(a.post("/api/v1/scans/ingest", env, format="json", **h).status_code, 400)

    def test_tenant_isolation(self):
        sid = self.upload().json()["scan_id"]
        _, _, _, other = make_tenant("B")
        self.assertEqual(other.get(f"/api/v1/scans/{sid}").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/scans/{sid}/export?fmt=json").status_code, 404)
        self.assertEqual(other.get("/api/v1/scans").json(), [])

    def test_revoked_agent_cannot_upload(self):
        self.c.post(f"/api/v1/agents/{self.ag['agent_id']}/revoke")
        self.assertEqual(self.upload().status_code, 401)

    def test_foreign_agent_scope(self):
        r = self.upload(tenant_id="00000000-0000-0000-0000-000000000000"); self.assertIn(r.status_code, (400, 403))

    def test_viewer_cannot_review(self):
        sid = self.upload().json()["scan_id"]; mid = M.BusinessMapping.objects.first().pk
        v = User.objects.create_user("v", password="x"); M.Membership.objects.create(tenant=self.t, user=v, role="viewer")
        c = APIClient(); c.force_authenticate(v)
        self.assertEqual(c.post(f"/api/v1/mappings/{mid}/review", {"decision": "accept"}, format="json").status_code, 403)


class FrontendSupport(Flow):
    def test_login_me_tables_graph_ids(self):
        r = APIClient().post("/api/v1/auth/login", {"username": "A", "password": "x"}, format="json")
        self.assertEqual(r.status_code, 200); tok = r.json()["token"]
        c = APIClient(); c.credentials(HTTP_AUTHORIZATION=f"Token {tok}")
        self.assertEqual(c.get("/api/v1/auth/me").json()["role"], "admin")
        sid = self.upload().json()["scan_id"]
        self.assertTrue(any("mapping_id" in n for n in c.get(f"/api/v1/scans/{sid}/graph").json()["nodes"]))
        self.assertTrue(c.get(f"/api/v1/scans/{sid}/tables").json()[0]["columns"])


class Deploy(Flow):
    def test_health_spa_sites_bootstrap(self):
        a = APIClient(); self.assertEqual(a.get("/api/v1/health").json(), {"status": "ok"})
        r = a.get("/scans/some-id"); self.assertEqual(r.status_code, 200); self.assertIn(b"UDME", r.content)  # SPA fallback, not 404
        self.assertEqual(a.get("/api/v1/nothing").status_code, 404)  # unknown API paths never fall into the SPA
        self.assertEqual(self.c.get("/api/v1/sites").json()[0]["name"], "Site")
        from django.core.management import call_command
        import os; os.environ["UDME_ADMIN_PASSWORD"] = "pw-test-123"
        call_command("bootstrap"); call_command("bootstrap")
        self.assertEqual(User.objects.filter(username="admin").count(), 1)
        self.assertEqual(M.Membership.objects.get(user__username="admin").role, "admin")

import json, sqlite3, tempfile, os, sys
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from django.test import TestCase
from udme_core.connectors import SQLAlchemyConnector
from udme_core.package import sign_envelope, generate_keypair
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
        self.priv, self.pub = generate_keypair()
        self.tok = tok; self.ag = APIClient().post("/api/v1/agents/enroll", {"token": tok, "public_key": self.pub}, format="json").json()

    def upload(self, **kw):
        env = sign_envelope(self.pkg, tenant_id=self.ag["tenant_id"], agent_id=self.ag["agent_id"],
                            scan_id=kw.pop("scan_id", "11111111-1111-1111-1111-111111111111"), private_key=kw.pop("secret", self.priv))
        env.update(kw); a = APIClient()
        return a.post("/api/v1/scans/ingest", env, format="json")

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
        r = APIClient().post("/api/v1/agents/enroll", {"token": self.tok, "public_key": generate_keypair()[1]}, format="json"); self.assertEqual(r.status_code, 403)

    def test_bad_signature_and_replay(self):
        self.assertEqual(self.upload(secret=generate_keypair()[0]).status_code, 400)  # signed with someone else's key
        env = sign_envelope(self.pkg, tenant_id=self.ag["tenant_id"], agent_id=self.ag["agent_id"], scan_id="22222222-2222-2222-2222-222222222222", private_key=self.priv)
        a = APIClient(); h = {}
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


class KeyHandling(Flow):
    def test_no_secret_on_server_and_bad_key_rejected(self):
        self.assertNotIn("secret", self.ag); self.assertEqual(M.Agent.objects.get().public_key, self.pub)
        r = APIClient().post("/api/v1/agents/enroll", {"token": "x", "public_key": "not-a-key"}, format="json"); self.assertEqual(r.status_code, 400)
        tok = self.c.post(f"/api/v1/sites/{self.site.pk}/enrollment-tokens").json()["token"]
        self.assertEqual(APIClient().post("/api/v1/agents/enroll", {"token": tok, "public_key": "bad"}, format="json").status_code, 400)
        self.assertEqual(APIClient().post("/api/v1/agents/enroll", {"token": tok, "public_key": generate_keypair()[1]}, format="json").status_code, 201)  # token survived the bad attempt

    def test_unknown_agent_same_answer_as_revoked(self):
        self.c.post(f"/api/v1/agents/{self.ag['agent_id']}/revoke"); a = self.upload().json()
        env = sign_envelope(self.pkg, tenant_id=self.ag["tenant_id"], agent_id="99999999-9999-9999-9999-999999999999", scan_id="44444444-4444-4444-4444-444444444444", private_key=self.priv)
        self.assertEqual(APIClient().post("/api/v1/scans/ingest", env, format="json").json(), a)


class CarryOver(Flow):
    def _scan(self, pkg, scan_id):
        env = sign_envelope(pkg, tenant_id=self.ag["tenant_id"], agent_id=self.ag["agent_id"], scan_id=scan_id, private_key=self.priv)
        r = APIClient().post("/api/v1/scans/ingest", env, format="json"); self.assertEqual(r.status_code, 202); return r.json()["scan_id"]

    def _edge(self, sid, src, col, tgt):
        g = self.c.get(f"/api/v1/scans/{sid}/graph").json()
        return next(e for e in g["edges"] if e["source_table"] == src and e["source_columns"] == [col] and e["target_table"] == tgt)

    def test_decisions_survive_next_scan_and_conflicts_are_not_silent(self):
        s1 = self._scan(self.pkg, "aaaaaaaa-0000-0000-0000-000000000001")
        rv = lambda kind, i, **b: self.assertEqual(self.c.post(f"/api/v1/{kind}/{i}/review", b, format="json").status_code, 200)
        rv("relationships", self._edge(s1, "main.T_LIGVTE", "ID_ART", "main.T_ART")["id"], decision="accept")
        rv("relationships", self._edge(s1, "main.T_STOCK", "ID_ART", "main.T_ART")["id"], decision="accept")
        rv("relationships", self._edge(s1, "main.T_ACHAT", "ID_FOUR", "main.T_FOUR")["id"], decision="reject")
        nodes = {n["id"]: n for n in self.c.get(f"/api/v1/scans/{s1}/graph").json()["nodes"]}
        rv("mappings", nodes["main.T_ART"]["mapping_id"], decision="accept")
        rv("mappings", nodes["main.T_FOUR"]["mapping_id"], decision="edit", label="procurement.wholesaler")

        pkg2 = self.pkg.model_copy(deep=True)  # schema evolves: T_STOCK loses ID_ART
        for sc in pkg2.schemas:
            for t in sc.tables:
                if t.name == "T_STOCK": t.columns = [c for c in t.columns if c.name != "ID_ART"]
        s2 = self._scan(pkg2, "aaaaaaaa-0000-0000-0000-000000000002")

        g = self.c.get(f"/api/v1/scans/{s2}/graph").json(); st = {(e["source_table"], e["source_columns"][0], e["target_table"]): e["status"] for e in g["edges"]}
        self.assertEqual(st[("main.T_LIGVTE", "ID_ART", "main.T_ART")], "accepted")      # decision carried
        self.assertEqual(st[("main.T_ACHAT", "ID_FOUR", "main.T_FOUR")], "rejected")     # rejection carried
        self.assertEqual(st[("main.T_STOCK", "ID_ART", "main.T_ART")], "conflict")       # vanished accepted relation: NOT silently dropped
        d = self.c.get(f"/api/v1/scans/{s2}").json(); self.assertEqual(d["conflicts"], 1); self.assertGreaterEqual(d["pending_reviews"], 1)
        n2 = {n["id"]: n for n in g["nodes"]}
        self.assertEqual((n2["main.T_ART"]["status"], n2["main.T_FOUR"]["label"], n2["main.T_FOUR"]["status"]), ("approved", "procurement.wholesaler", "edited"))
        self.assertTrue(M.AuditEvent.objects.filter(action="scan.decisions_carried", details__conflicts=1).exists())

        csv = self.c.get(f"/api/v1/scans/{s2}/export?fmt=csv").content.decode()
        self.assertNotIn("T_ACHAT,ID_FOUR,main.T_FOUR", csv); self.assertIn("conflict", csv)       # export honours reviews
        md = self.c.get(f"/api/v1/scans/{s2}/export?fmt=md").content.decode()
        self.assertIn("procurement.wholesaler", md); self.assertIn("approved by reviewer", md)

    def test_first_scan_has_nothing_to_carry(self):
        s1 = self._scan(self.pkg, "bbbbbbbb-0000-0000-0000-000000000001")
        self.assertEqual(M.AuditEvent.objects.get(action="scan.decisions_carried").details["from"], None)


from django.test import override_settings


@override_settings(ALLOWED_HOSTS=["udme.onrender.com", "testserver"])
class HealthHost(Flow):
    def test_health_ignores_host_and_https_redirect(self):
        from django.test import Client
        r = Client().get("/api/v1/health", HTTP_HOST="10.1.2.3:10000"); self.assertEqual((r.status_code, r.json()["status"]), (200, "ok"))
        self.assertEqual(Client().get("/api/v1/scans", HTTP_HOST="evil.example").status_code, 400)  # other paths still host-checked

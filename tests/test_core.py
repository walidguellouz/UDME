import os, sqlite3, time, pytest
from make_fixture import build
from udme_core.connectors import SQLAlchemyConnector
from udme_core.pipeline import analyze, diff
from udme_core.package import sign_envelope, verify_envelope, schema_hash, generate_keypair
from udme_core.fingerprint import Evidence, fingerprint
from udme_core import exporters as ex

@pytest.fixture
def pkg(tmp_path):
    p = tmp_path / "t.db"; build(str(p))
    con = SQLAlchemyConnector(f"sqlite:///{p}")
    pk = con.extract("WinGest"); con.close(); return pk, p

def rels(pkg): return {(r.source_table, r.source_columns[0], r.target_table): r for r in analyze(pkg).relationships}

def test_extract_and_inference(pkg):
    pk, _ = pkg; r = rels(pk)
    assert r[("main.T_LIGVTE", "ID_ART", "main.T_ART")].score >= 0.9
    assert r[("main.T_LIGVTE", "ID_VTE", "main.T_VTE")].candidate_type == "one_to_many"
    assert r[("main.T_ACHAT", "ID_FOUR", "main.T_FOUR")].declared is False
    d = r[("main.ORDERS", "customer_id", "main.CUSTOMERS")]; assert d.declared and d.score == 1.0 and d.status == "accepted"
    assert not any(k[1] == "ID_LIG" for k in r)  # PKs never become FK candidates

def test_mapper_unknown_and_labels(pkg):
    m = {x.object_id: x for x in analyze(pkg[0]).mappings}
    assert m["main.T_ART"].label == "catalog.product" and m["main.T_ART"].review_required
    assert m["main.T_FOUR"].label == "procurement.supplier"
    assert m["main.ZZ_MISC"].label == "UNKNOWN"
    assert all(x.confidence < 0.95 for x in m.values())  # rules alone never "very high"

def test_read_only_enforced(pkg):
    _, p = pkg
    con = SQLAlchemyConnector(f"sqlite:///{p}")
    with pytest.raises(Exception):
        with con.engine.begin() as c: c.exec_driver_sql("CREATE TABLE x(a)")
    con.close()

def test_fail_closed_without_ro_proof(monkeypatch):
    import udme_core.connectors.sqlalchemy_connector as sc
    monkeypatch.setattr(sc, "create_engine", lambda *a, **k: object())
    con = SQLAlchemyConnector("mssql+pyodbc://u:p@host/db")
    assert con.verify_read_only().verified is False
    with pytest.raises(PermissionError): con.extract()

def test_hash_stable_and_diff(pkg):
    pk, p = pkg
    time.sleep(1.1)
    c = SQLAlchemyConnector(f"sqlite:///{p}"); pk2 = c.extract("WinGest"); c.close()
    assert schema_hash(pk) == schema_hash(pk2)
    q = sqlite3.connect(p); q.execute("ALTER TABLE T_ART ADD COLUMN NEWCOL TEXT"); q.commit(); q.close()
    c = SQLAlchemyConnector(f"sqlite:///{p}"); pk3 = c.extract(); c.close()
    assert diff(pk, pk3)["columns_changed"]["main.T_ART"]["added"] == ["NEWCOL"]

def test_envelope_security(pkg):
    pk, _ = pkg
    priv, pub = generate_keypair()
    env = sign_envelope(pk, tenant_id="t", agent_id="a", scan_id="s", private_key=priv)
    assert verify_envelope(env, pub).source.engine == "sqlite"
    with pytest.raises(ValueError, match="bad_signature"): verify_envelope(env, generate_keypair()[1])
    with pytest.raises(ValueError, match="bad_signature"): verify_envelope(dict(env, scan_id="other"), pub)  # signed fields are tamper-evident
    env2 = dict(env, package=env["package"] + " ")
    with pytest.raises(ValueError, match="bad_checksum"): verify_envelope(env2, pub)
    with pytest.raises(ValueError, match="stale"): verify_envelope(dict(env, created_at=1), pub)

def test_fingerprint(pkg):
    _, p = pkg
    r = fingerprint(Evidence(selected_files=[str(p)])); assert r["decision"] == "sqlite"
    assert fingerprint(Evidence(selected_files=["x.fdb"]))["decision"] == "NEEDS_USER_CONFIRMATION"  # extension alone is never enough
    amb = fingerprint(Evidence(config_text={"a.ini": "sqloledb firebird"}))
    assert amb["decision"] == "NEEDS_USER_CONFIRMATION"

def test_exports(pkg):
    a = analyze(pkg[0]); md = ex.to_markdown(a.package, a.relationships, a.mappings)
    assert "erDiagram" in md and "catalog.product" in md
    assert "CREATE TABLE" in ex.to_ddl(a.package)


def test_wingest_profile(tmp_path):
    from udme_core.profiles import wingest
    d = tmp_path / "WinGest"; d.mkdir()
    r = wingest.discover(str(d)); assert r["gate1_ready"] is False and r["checklist_appendix_a"]["4_db_engine"]["confirmed"] is False
    with pytest.raises(RuntimeError, match="ENGINE_AMBIGUOUS"): wingest.resolve_engine(str(d), None)  # never guess
    (d / "data.fdb").write_bytes(b"x" * 10)  # extension alone: still not enough
    with pytest.raises(RuntimeError): wingest.resolve_engine(str(d), None)
    (d / "app.ini").write_text("[DB]\nlib=fbclient.dll\nport=3050\nuser=SYSDBA\npassword=secret\n")
    r = wingest.discover(str(d)); assert r["fingerprint"]["decision"] == "firebird"
    assert "secret" not in str(r)  # config content never reported
    assert wingest.resolve_engine(str(d), None) == ("firebird", "fingerprint")
    assert wingest.resolve_engine(str(d), "sqlserver")[1] == "operator_confirmed"
    assert "firebird+fdb://u:p%40ss@h:3050/db" == wingest.build_url("firebird", user="u", password="p@ss", host="h", database="db")

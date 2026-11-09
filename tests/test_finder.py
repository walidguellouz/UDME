import os, sqlite3
from udme_core.finder import find_databases
from udme_agent import picker

def tree(tmp):
    def w(rel, data=b"x"):
        p = tmp / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); return p
    sq = tmp / "WinGest" / "data" / "app.db"; sq.parent.mkdir(parents=True); sqlite3.connect(sq).execute("create table a(x)").connection.close()
    w("Docs/old.mdb", b"\x00\x01\x00\x00Standard Jet DB\x00" + b"0" * 20)
    w("Data/x.fdb"); w("Dump/s.sql", b"-- dump\nCREATE TABLE t (a int);\nINSERT INTO t VALUES (1);")
    w("Dump/notes.sql", b"select 1"); w("Pics/Thumbs.db"); w("Pics/fake.db", b"not sqlite at all")
    w("AppData/Local/Google/Chrome/User Data/History.sqlite", b"SQLite format 3\x00" + b"0" * 20)
    w("node_modules/pkg/skip.sqlite", b"SQLite format 3\x00"); w("backup/full.bak", b"TAPE" + b"0" * 30)
    os.symlink(tmp / "Data", tmp / "linkdir")
    return sq

def test_find(tmp_path):
    sq = tree(tmp_path); r = find_databases([str(tmp_path)]); paths = [c.path for c in r]; names = [os.path.basename(p) for p in paths]
    assert paths[0] == str(sq) and r[0].kind == "sqlite" and r[0].header_verified          # WinGest-named path + verified header first
    assert {"old.mdb", "x.fdb", "s.sql", "full.bak"} <= set(names)
    assert "notes.sql" not in names and "Thumbs.db" not in names and "fake.db" not in names  # false positives discarded
    assert "History.sqlite" not in names and "skip.sqlite" not in names                       # browser noise / skipped dirs hidden
    assert names.count("x.fdb") == 1                                                          # symlink not followed
    kinds = {os.path.basename(c.path): c for c in r}
    assert kinds["old.mdb"].kind == "access" and kinds["x.fdb"].header_verified is False and kinds["full.bak"].kind == "sqlserver_backup"
    assert "History.sqlite" in [os.path.basename(c.path) for c in find_databases([str(tmp_path)], include_noise=True)]

def test_never_modifies_and_stores_no_content(tmp_path):
    tree(tmp_path); before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    r = find_databases([str(tmp_path)]); assert before == {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert "CREATE TABLE" not in str([c.to_dict() for c in r])

def test_cancel_and_cap(tmp_path):
    tree(tmp_path); import threading; e = threading.Event(); e.set()
    assert find_databases([str(tmp_path)], cancel=e) == []
    assert len(find_databases([str(tmp_path)], max_entries=1)) <= 1

def test_operator_must_choose(tmp_path):
    sq = tree(tmp_path); r = find_databases([str(tmp_path)]); out = []
    ans = iter(["1", "n", "q"]); assert picker.choose(r, input_fn=lambda _: next(ans), out=out.append) is None   # declined confirmation, then quit
    ans = iter(["99", "1", "o"]); assert picker.choose(r, input_fn=lambda _: next(ans), out=out.append) == str(sq)

def test_proceed_sqlite_needs_consent_and_nonsqlite_never_scans(tmp_path):
    sq = tree(tmp_path); called = []
    res = picker.proceed(str(sq), input_fn=lambda _: "n", out=lambda *_: None, run_scan=lambda: called.append(1)); assert not called and not res["scanned"]
    picker.proceed(str(sq), input_fn=lambda _: "o", out=lambda *_: None, run_scan=lambda: called.append(1)); assert called
    out = []; res = picker.proceed(str(tmp_path / "Data" / "x.fdb"), input_fn=lambda _: "o", out=out.append, run_scan=lambda: called.append(2))
    assert 2 not in called and any("COPIE" in str(o) for o in out)       # extension-only engine: warn, never auto-scan

def test_sql_dump_is_never_executed_or_scanned(tmp_path):
    dump = tmp_path / "schema.sql"; dump.write_text("CREATE TABLE example (id INTEGER);")
    called = []; out = []
    result = picker.proceed(str(dump), out=out.append, run_scan=lambda: called.append(True))
    assert not result["scanned"] and not called
    assert any("ne l'exécute pas" in message for message in out)

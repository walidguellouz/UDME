"""UDME local discovery agent (CLI). Read-only, metadata-only.
Commands: discover | scan | analyze | diff.
DB URL is read from env UDME_DB_URL (never a CLI arg, so it stays out of shell history/logs)."""
from __future__ import annotations
import argparse, json, os, stat, sys, time, urllib.request, uuid
import urllib.error
from pathlib import Path
from udme_core.fingerprint import Evidence, fingerprint, windows_installed_apps, windows_services
from udme_core.connectors import SQLAlchemyConnector
from udme_core.pipeline import analyze, diff
from udme_core.model import Package
from udme_core.package import sign_envelope, generate_keypair
from udme_core import exporters as ex
from udme_core.finder import find_databases
from . import picker
from udme_core.profiles import wingest


CONF = Path(os.environ.get("UDME_HOME", Path.home() / ".udme")) / "agent.json"


def load_conf() -> dict:
    try: return json.loads(CONF.read_text())
    except OSError: return {}


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r: return r.status, r.read().decode()


def cmd_enroll(a):
    """One-time enrollment: exchange the short-lived token (from the web portal) for a revocable device credential."""
    server = a.server.rstrip("/")
    priv, pub = generate_keypair()  # private key stays on this machine
    try: _, body = _post(f"{server}/api/v1/agents/enroll", {"token": a.token, "public_key": pub, "name": a.name or os.environ.get("COMPUTERNAME", "agent")})
    except urllib.error.HTTPError as e: sys.exit(f"Enrôlement refusé ({e.code}) : jeton invalide, expiré ou déjà utilisé.")
    d = json.loads(body); CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps({"server": server, "tenant_id": d["tenant_id"], "agent_id": d["agent_id"], "private_key": priv}))
    try: os.chmod(CONF, stat.S_IRUSR | stat.S_IWUSR)  # POSIX 600; on Windows the profile ACL applies
    except OSError: pass
    print(f"Agent enrôlé ({d['agent_id']}). Identifiants enregistrés dans {CONF}")


def cmd_discover(a):
    ev = Evidence(selected_files=a.path or [], services=windows_services(),
                  installed_apps=windows_installed_apps("wingest"))
    for p in a.config or []:  # parsed locally; raw text never leaves the machine
        ev.config_text[Path(p).name] = Path(p).read_text(errors="ignore")[:200_000]
    res = fingerprint(ev); res["installed_apps"] = ev.installed_apps
    print(json.dumps(res, indent=2))


def cmd_scan(a):
    url = os.environ.get("UDME_DB_URL")
    if not url: sys.exit("Set UDME_DB_URL (SQLAlchemy URL of a READ-ONLY account).")
    con = SQLAlchemyConnector(url, confirm_read_only_account=a.confirm_read_only)
    try:
        con.validate_connection()
        pkg = con.extract(product_hint=a.product_hint)
    except PermissionError as e:
        sys.exit(str(e))
    finally:
        con.close()
    res = analyze(pkg)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "package.json").write_text(pkg.model_dump_json(indent=2))
    (out / "mapping.json").write_text(ex.to_json(pkg, res.relationships, res.mappings))
    (out / "relationships.csv").write_text(ex.relationships_csv(res.relationships))
    (out / "dictionary.md").write_text(ex.to_markdown(pkg, res.relationships, res.mappings))
    (out / "schema.ddl.sql").write_text(ex.to_ddl(pkg))
    n = sum(1 for _ in pkg.iter_tables())
    print(f"OK: {n} objects, {len(res.relationships)} relationships, schema_hash={res.schema_hash[:12]} -> {out}")
    if a.upload:
        c = load_conf(); g = lambda k: os.environ.get("UDME_" + k.upper()) or c.get(k)
        if not (g("tenant_id") and g("agent_id") and g("private_key")): sys.exit("Agent non enrôlé : lancez d'abord `udme-agent enroll --server URL --token JETON`.")
        url = c.get("server", "").rstrip("/") + "/api/v1/scans/ingest" if a.upload == "auto" else a.upload
        env = sign_envelope(pkg, tenant_id=g("tenant_id"), agent_id=g("agent_id"), scan_id=str(uuid.uuid4()), private_key=g("private_key"))
        try: st, body = _post(url, env)
        except urllib.error.HTTPError as e: sys.exit(f"Envoi refusé ({e.code}) : {e.read().decode()[:200]}")
        print("Envoyé :", st, body[:200])


def cmd_wingest_discover(a):
    print(json.dumps(wingest.discover(a.dir), indent=2, ensure_ascii=False))


def cmd_wingest_scan(a):
    """Gate 1: refuses to scan unless the engine is established by evidence or explicit operator decision."""
    try:
        engine, basis = wingest.resolve_engine(a.dir, a.engine)
    except (RuntimeError, ValueError) as e:
        sys.exit(str(e))
    print(f"Engine: {engine} (basis: {basis}). Driver needed: {wingest.EXTRA_PACKAGES[engine]}")
    if not os.environ.get("UDME_DB_URL"):
        sys.exit("Set UDME_DB_URL, e.g. template: " + wingest.URL_TEMPLATES[engine])
    a.product_hint = "WinGest"; a.f = cmd_scan; cmd_scan(a)


def cmd_find(a):
    """Find every database-like file on this PC, let the operator choose, then continue (or just list with --json)."""
    if a.gui:
        from .gui import pick_with_gui
        path = pick_with_gui(a.root, a.include_noise)
    else:
        print("Recherche locale des fichiers de base de données (en-têtes uniquement, rien n'est envoyé)… Ctrl+C pour arrêter.", file=sys.stderr)
        last = [0.0]
        def prog(n, f, d):
            if time.time() - last[0] > 1: last[0] = time.time(); print(f"\r{n:,} éléments · {f} trouvé(s)   ", end="", file=sys.stderr)
        try: cands = find_databases(a.root, include_noise=a.include_noise, include_removable=a.include_removable,
                                    max_seconds=a.max_minutes * 60, progress=prog)
        except KeyboardInterrupt: sys.exit("Interrompu.")
        print(file=sys.stderr)
        if a.json: print(json.dumps([c.to_dict() for c in cands], indent=2, ensure_ascii=False)); return
        if not cands: sys.exit("Aucun fichier trouvé. Utilisez --root <dossier> ou --include-noise / --include-removable.")
        path = picker.choose(cands)
    if not path: sys.exit("Aucun fichier choisi. Rien n'a été exécuté.")
    print(f"\nFichier choisi : {path}")
    out = a.out
    picker.proceed(path, run_scan=lambda: cmd_scan(argparse.Namespace(out=out, product_hint=a.product_hint, confirm_read_only=False, upload=None)))


def cmd_analyze(a):
    pkg = Package.model_validate_json(Path(a.package).read_text())
    res = analyze(pkg); print(ex.to_markdown(pkg, res.relationships, res.mappings))


def cmd_diff(a):
    p = lambda f: Package.model_validate_json(Path(f).read_text())
    print(json.dumps(diff(p(a.old), p(a.new)), indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser("udme-agent"); sub = ap.add_subparsers(required=True)
    d = sub.add_parser("discover"); d.add_argument("--path", nargs="*"); d.add_argument("--config", nargs="*"); d.set_defaults(f=cmd_discover)
    en = sub.add_parser("enroll"); en.add_argument("--server", required=True, help="ex. https://udme.onrender.com")
    en.add_argument("--token", required=True); en.add_argument("--name"); en.set_defaults(f=cmd_enroll)
    s = sub.add_parser("scan"); s.add_argument("--out", default="udme_out"); s.add_argument("--product-hint", default=None)
    s.add_argument("--confirm-read-only", action="store_true"); s.add_argument("--upload", nargs="?", const="auto", help="envoyer au serveur enrôlé (ou URL explicite)")
    s.set_defaults(f=cmd_scan)
    w = sub.add_parser("wingest-discover"); w.add_argument("--dir", help="WinGest install folder selected by the customer"); w.set_defaults(f=cmd_wingest_discover)
    ws = sub.add_parser("wingest-scan"); ws.add_argument("--dir"); ws.add_argument("--engine", choices=wingest.ENGINES)
    ws.add_argument("--out", default="udme_out"); ws.add_argument("--confirm-read-only", action="store_true"); ws.add_argument("--upload", nargs="?", const="auto")
    ws.set_defaults(f=cmd_wingest_scan)
    fd = sub.add_parser("find-databases", help="chercher les bases sur ce PC et choisir le fichier")
    fd.add_argument("--root", nargs="*", help="dossiers/disques à parcourir (défaut : tous les disques fixes)")
    fd.add_argument("--include-noise", action="store_true", help="inclure navigateurs/système")
    fd.add_argument("--include-removable", action="store_true"); fd.add_argument("--max-minutes", type=float, default=15)
    fd.add_argument("--gui", action="store_true", help="fenêtre de sélection"); fd.add_argument("--json", action="store_true", help="liste seule, non interactif")
    fd.add_argument("--out", default="udme_out"); fd.add_argument("--product-hint", default=None); fd.set_defaults(f=cmd_find)
    an = sub.add_parser("analyze"); an.add_argument("package"); an.set_defaults(f=cmd_analyze)
    df = sub.add_parser("diff"); df.add_argument("old"); df.add_argument("new"); df.set_defaults(f=cmd_diff)
    a = ap.parse_args(argv); a.f(a)


if __name__ == "__main__":
    main()

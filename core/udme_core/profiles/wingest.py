"""WinGest profile pack (plan 2.1 / Appendix A).

IMPORTANT: nothing here asserts WinGest's real engine or schema. These are *discovery hints* and a
checklist generator. The engine must be confirmed on an authorized installation (Gate 1) — either by
fingerprint evidence that is unambiguous, or by an explicit operator decision (`engine=`).
Only files inside the folder the user selected are read, depth <= 2, small text files only, locally.
"""
from __future__ import annotations
import os
from pathlib import Path
from ..fingerprint import Evidence, fingerprint, windows_installed_apps, windows_services, ENGINES

PRODUCT = "WinGest"
REGISTRY_NEEDLE = "wingest"
CONFIG_EXT = {".ini", ".cfg", ".config", ".xml", ".udl", ".conf", ".json"}
DB_EXT = {".mdb", ".accdb", ".fdb", ".gdb", ".db", ".sqlite", ".mdf", ".ndf", ".bak", ".dbf"}
MAX_CFG_BYTES, MAX_DEPTH, MAX_FILES = 200_000, 2, 2000

# SQLAlchemy URL templates per candidate engine. Drivers must be installed separately; account must be read-only.
URL_TEMPLATES = {
    "sqlserver": "mssql+pyodbc://{user}:{password}@{host}/{database}?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes",
    "firebird": "firebird+fdb://{user}:{password}@{host}:{port}/{database}",
    "access": "access+pyodbc:///?odbc_connect=DRIVER%3D%7BMicrosoft+Access+Driver+%28*.mdb%2C+*.accdb%29%7D%3BDBQ%3D{path}%3BReadOnly%3D1",
    "sqlite": "sqlite:///{path}",
    "mysql": "mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
    "postgresql": "postgresql+psycopg://{user}:{password}@{host}:{port}/{database}",
}
EXTRA_PACKAGES = {"sqlserver": "pyodbc", "firebird": "sqlalchemy-firebird + fdb", "access": "pyodbc + sqlalchemy-access (32/64-bit must match the ODBC driver)",
                  "mysql": "pymysql", "postgresql": "psycopg", "sqlite": "(built in)"}

# French/English vocabulary additions for the mapper (candidate hints only, NOT verified field names).
VOCAB_HINTS = {"catalog.product": ["specialite", "dci", "cip", "laboratoire"], "customers.customer": ["mutuelle", "assure", "ordonnance"],
               "procurement.supplier": ["grossiste", "repartiteur"]}


def _walk(root: Path):
    n = 0
    for dp, dn, fn in os.walk(root):
        depth = Path(dp).relative_to(root).parts.__len__()
        if depth >= MAX_DEPTH: dn[:] = []
        for f in fn:
            n += 1
            if n > MAX_FILES: return
            yield Path(dp) / f


def collect_evidence(install_dir: str | None) -> tuple[Evidence, dict]:
    ev = Evidence(services=windows_services(), installed_apps=windows_installed_apps(REGISTRY_NEEDLE))
    facts = {"db_like_files": [], "config_files_read": [], "skipped": []}
    if install_dir:
        root = Path(install_dir)
        if not root.is_dir(): raise FileNotFoundError(install_dir)
        for p in _walk(root):
            ext = p.suffix.lower()
            if ext in DB_EXT:
                ev.selected_files.append(str(p)); facts["db_like_files"].append({"name": p.name, "bytes": p.stat().st_size})
            elif ext in CONFIG_EXT:
                if p.stat().st_size > MAX_CFG_BYTES: facts["skipped"].append(p.name); continue
                ev.config_text[p.name] = p.read_text(errors="ignore")  # parsed locally, never uploaded
                facts["config_files_read"].append(p.name)
    return ev, facts


def discover(install_dir: str | None) -> dict:
    """Return fingerprint + Appendix-A checklist pre-filled with what is *observed*; the rest is TO_VERIFY."""
    ev, facts = collect_evidence(install_dir)
    fp = fingerprint(ev); TV = "TO_VERIFY"
    top = fp["candidates"][0]["engine"] if fp["candidates"] else None
    return {
        "product": PRODUCT, "fingerprint": fp, "facts": facts,
        "gate1_ready": fp["decision"] in ENGINES,
        "next_step": ("Engine fingerprint is unambiguous — still confirm it with the customer, then run: scan --engine "
                      f"{fp['decision']}") if fp["decision"] in ENGINES else
                     "Engine NOT established. Confirm with the vendor/customer (or native tooling) and pass --engine explicitly. Do not guess.",
        "checklist_appendix_a": {
            "1_product_version": ev.installed_apps or TV, "2_windows_version": TV, "3_install_dir_selected": install_dir or TV,
            "4_db_engine": {"observed_top_candidate": top, "confirmed": False}, "5_db_location": TV, "6_driver_bitness": TV,
            "7_backup_mechanism": TV, "8_read_only_login": TV, "9_catalog_permissions": TV, "10_schema_size": TV,
            "11_fk_declared": TV, "12_views_routines_triggers": TV, "13_naming_language": TV,
            "14_vendor_licence_restrictions": "Written approval required before inspection beyond customer-authorized access",
            "15_synthetic_db_available": TV},
        "driver_hint": EXTRA_PACKAGES.get(top) if top else None,
    }


def build_url(engine: str, **p) -> str:
    if engine not in URL_TEMPLATES: raise ValueError(f"unsupported engine: {engine}")
    from urllib.parse import quote_plus
    q = {k: (quote_plus(str(v)) if k in ("user", "password") else v) for k, v in p.items()}
    q.setdefault("port", {"firebird": 3050, "mysql": 3306, "postgresql": 5432}.get(engine, ""))
    return URL_TEMPLATES[engine].format(**q)


def resolve_engine(install_dir: str | None, operator_engine: str | None) -> tuple[str, str]:
    """Gate 1 enforcement: returns (engine, basis). Raises if neither evidence nor operator decision exists."""
    if operator_engine:
        if operator_engine not in ENGINES: raise ValueError(f"unknown engine {operator_engine}")
        return operator_engine, "operator_confirmed"
    fp = discover(install_dir)["fingerprint"]
    if fp["decision"] in ENGINES: return fp["decision"], "fingerprint"
    raise RuntimeError(f"ENGINE_AMBIGUOUS: {fp.get('reason')}. Pass --engine after confirming it on the authorized installation.")

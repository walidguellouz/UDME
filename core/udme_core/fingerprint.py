"""Engine fingerprinting (plan 6.1). Weights are provisional — calibrate on
labelled installations. A file extension alone never establishes identity."""
from __future__ import annotations
import os, re
from dataclasses import dataclass, field

MIN_CONFIDENCE, AMBIGUITY_MARGIN = 0.50, 0.15
SQLITE_MAGIC = b"SQLite format 3\x00"
ENGINES = ["sqlite", "access", "sqlserver", "firebird", "mysql", "postgresql"]
EXT = {".sqlite": "sqlite", ".db": "sqlite", ".mdb": "access", ".accdb": "access", ".fdb": "firebird", ".gdb": "firebird"}
CONFIG_HINTS = {  # non-secret keyword hints only
    "sqlserver": [r"sqloledb", r"sqlncli", r"msoledbsql", r"sql server", r"\b1433\b"],
    "firebird": [r"firebird", r"fbclient", r"\b3050\b", r"interbase"],
    "access": [r"microsoft\.jet", r"microsoft\.ace", r"\.mdb\b", r"\.accdb\b"],
    "mysql": [r"mysql", r"mariadb", r"\b3306\b"],
    "postgresql": [r"postgres", r"\b5432\b"],
    "sqlite": [r"sqlite"],
}
SERVICE_HINTS = {"sqlserver": ["mssql", "sqlservr"], "firebird": ["firebird", "fbserver", "fbguard"],
                 "mysql": ["mysqld", "mariadb"], "postgresql": ["postgres"]}


@dataclass
class Evidence:
    selected_files: list[str] = field(default_factory=list)
    config_text: dict[str, str] = field(default_factory=dict)  # parsed locally, never uploaded
    services: list[str] = field(default_factory=list)
    installed_apps: list[str] = field(default_factory=list)


def file_signature(path: str) -> str | None:
    try:
        with open(path, "rb") as f: head = f.read(32)
    except OSError:
        return None
    if head.startswith(SQLITE_MAGIC): return "sqlite"
    if head[4:19] in (b"Standard Jet DB", b"Standard ACE DB"): return "access"
    return None


def fingerprint(ev: Evidence) -> dict:
    scores = {e: {"score": 0.0, "evidence": []} for e in ENGINES}
    for p in ev.selected_files:
        sig = file_signature(p)
        if sig: scores[sig]["score"] += 0.60; scores[sig]["evidence"].append(f"file_signature:{os.path.basename(p)}")
        e = EXT.get(os.path.splitext(p)[1].lower())
        if e: scores[e]["score"] += 0.15; scores[e]["evidence"].append("extension_hint(weak)")
    for fname, txt in ev.config_text.items():
        for eng, pats in CONFIG_HINTS.items():
            hits = [p for p in pats if re.search(p, txt, re.I)]
            if hits: scores[eng]["score"] += min(0.25 * len(hits), 0.50); scores[eng]["evidence"].append(f"config_hint:{fname}")
    for svc in ev.services:
        for eng, keys in SERVICE_HINTS.items():
            if any(k in svc.lower() for k in keys): scores[eng]["score"] += 0.30; scores[eng]["evidence"].append(f"service:{svc}")
    ranked = sorted(((e, min(v["score"], 1.0), v["evidence"]) for e, v in scores.items() if v["score"] > 0),
                    key=lambda x: -x[1])
    res = {"candidates": [{"engine": e, "score": round(s, 2), "evidence": ev_} for e, s, ev_ in ranked]}
    if not ranked or ranked[0][1] < MIN_CONFIDENCE:
        res["decision"] = "NEEDS_USER_CONFIRMATION"; res["reason"] = "low_confidence"
    elif len(ranked) > 1 and ranked[0][1] - ranked[1][1] < AMBIGUITY_MARGIN:
        res["decision"] = "NEEDS_USER_CONFIRMATION"; res["reason"] = "ENGINE_AMBIGUOUS"
    else:
        res["decision"] = ranked[0][0]
    return res


def windows_installed_apps(needle: str = "wingest") -> list[str]:
    """Read uninstall registry keys (names only). No-op off Windows."""
    try:
        import winreg  # type: ignore
    except ImportError:
        return []
    found = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(root, sub) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                            try: name = winreg.QueryValueEx(s, "DisplayName")[0]
                            except OSError: continue
                            if needle.lower() in name.lower(): found.append(name)
            except OSError:
                continue
    return found


def windows_services() -> list[str]:
    try:
        import psutil  # type: ignore
        return [s.name() for s in psutil.win_service_iter()]
    except Exception:
        return []

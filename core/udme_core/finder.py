"""Local database-file finder (operator-initiated, read-only, local-only).

What it does: walks the disks of THIS machine, and for files whose extension looks like a database it
reads only the first bytes (magic number). For .sql it checks the first 4 KB for DDL/DML keywords and
keeps only a yes/no — content is never stored or displayed. Nothing is uploaded. Files are never
modified. Symlinks are not followed. Unreadable/locked files are listed as 'locked' (skipped, no retry).
"""
from __future__ import annotations
import os, re, threading, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

EXT_KIND = {".sqlite": "sqlite", ".sqlite3": "sqlite", ".db3": "sqlite", ".db": "sqlite", ".mdb": "access", ".accdb": "access",
            ".mdf": "sqlserver", ".ndf": "sqlserver", ".bak": "backup", ".fdb": "firebird", ".gdb": "firebird", ".ib": "interbase",
            ".dbf": "dbase/foxpro", ".ibd": "mysql-innodb", ".myd": "mysql-myisam", ".duckdb": "duckdb", ".sql": "sql_dump",
            ".dump": "pg_dump", ".backup": "pg_dump"}
SQLITE_MAGIC = b"SQLite format 3\x00"
SKIP_DIRS = {"$recycle.bin", "system volume information", "winsxs", "node_modules", ".git", "__pycache__", "site-packages", "$windows.~bt"}
SKIP_AT_ROOT = {"windows", "proc", "sys", "dev", "run", "snap"}
NOISE_FRAGMENTS = ("google/chrome", "chromium", "mozilla/firefox", ".mozilla", "microsoft/edge", "appdata/local/packages", "appdata/local/microsoft",
                   "programdata/microsoft", "/.cache/", "thumbs.db", "/library/application support/", "/.config/", "dropbox/.dropbox", "onedrive/.")
HINTS = {"wingest": 100, "winpharma": 30, "pharma": 30, "officine": 30, "pharm": 15}
SQL_RE = re.compile(rb"\b(CREATE\s+(TABLE|DATABASE)|INSERT\s+INTO|DROP\s+TABLE)\b", re.I)


@dataclass
class Candidate:
    path: str; size: int; modified: float; ext: str; kind: str
    header_verified: bool = False; noise: bool = False; locked: bool = False; score: int = 0
    def to_dict(self): return asdict(self)


def fixed_drives(include_removable: bool = False) -> list[str]:
    if os.name != "nt": return [str(Path.home())]
    import ctypes, string
    k = ctypes.windll.kernel32; mask = k.GetLogicalDrives(); out = []
    for i, l in enumerate(string.ascii_uppercase):
        if mask >> i & 1:
            t = k.GetDriveTypeW(f"{l}:\\")  # 3 = fixed, 2 = removable; network (4) never scanned
            if t == 3 or (include_removable and t == 2): out.append(f"{l}:\\")
    return out


def _inspect(path: str, ext: str) -> Candidate | None:
    try: st = os.stat(path)
    except OSError: return None
    low = path.replace("\\", "/").lower()
    c = Candidate(path=path, size=st.st_size, modified=st.st_mtime, ext=ext, kind=EXT_KIND[ext],
                  noise=any(n in low for n in NOISE_FRAGMENTS))
    try:
        with open(path, "rb") as f: head = f.read(4096 if ext == ".sql" else 32)
    except OSError:
        c.locked = True; head = b""   # in use / no permission: do not retry or copy
    if head.startswith(SQLITE_MAGIC): c.kind, c.header_verified = "sqlite", True
    elif head[4:19] in (b"Standard Jet DB", b"Standard ACE DB"): c.kind, c.header_verified = "access", True
    elif ext in (".bak",) and head[:4] == b"TAPE": c.kind, c.header_verified = "sqlserver_backup", True
    elif head[:5] == b"PGDMP": c.kind, c.header_verified = "pg_dump", True
    elif ext == ".sql":
        if not SQL_RE.search(head) and not c.locked: return None  # not an SQL dump: discard
        c.header_verified = bool(head)
    elif ext == ".db" and not c.locked:
        if c.noise or "wingest" not in low: return None  # ".db" without SQLite magic = not a database we can name
        c.kind = "unknown(.db, chemin WinGest)"
    elif ext == ".bak" and not c.header_verified: c.kind = "backup(unknown format)"
    s = sum(v for k, v in HINTS.items() if k in low) + (20 if c.header_verified else 0) - (50 if c.noise else 0)
    c.score = s
    return c


def find_databases(roots: list[str] | None = None, *, include_noise: bool = False, include_removable: bool = False,
                   max_seconds: float = 900, max_entries: int = 5_000_000, cancel: threading.Event | None = None,
                   progress: Callable[[int, int, str], None] | None = None) -> list[Candidate]:
    roots = roots or fixed_drives(include_removable)
    found: list[Candidate] = []; seen = 0; t0 = time.time()
    for root in roots:
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            if cancel and cancel.is_set(): return _sorted(found, include_noise)
            if time.time() - t0 > max_seconds or seen > max_entries: return _sorted(found, include_noise)
            try: it = list(os.scandir(d))
            except OSError: continue  # permission denied etc.
            for e in it:
                seen += 1
                try:
                    if e.is_symlink(): continue
                    if e.is_dir(follow_symlinks=False):
                        n = e.name.lower()
                        if n in SKIP_DIRS or (depth == 0 and n in SKIP_AT_ROOT): continue
                        stack.append((e.path, depth + 1))
                    elif e.is_file(follow_symlinks=False):
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in EXT_KIND and (c := _inspect(e.path, ext)): found.append(c)
                except OSError: continue
            if progress and seen % 5000 < len(it): progress(seen, len(found), d)
    return _sorted(found, include_noise)


def _sorted(found: list[Candidate], include_noise: bool) -> list[Candidate]:
    f = [c for c in found if include_noise or not c.noise]
    return sorted(f, key=lambda c: (-c.score, -c.size))

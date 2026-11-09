"""Interactive selection + guided continuation. The operator ALWAYS chooses the file; nothing runs before that."""
from __future__ import annotations
import os, sys, time
from udme_core.finder import Candidate
from udme_core.fingerprint import Evidence, fingerprint
from udme_core.profiles import wingest

LIVE_WARNING = ("⚠ Ne travaillez pas sur un fichier en cours d'utilisation par le logiciel (Access/Firebird/SQL Server) : "
                "utilisez une COPIE ou une sauvegarde faite avec l'outil de l'éditeur.")


def human(n: int) -> str:
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024: return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def show(cands: list[Candidate], limit: int = 60, out=print):
    out(f"\n{len(cands)} fichier(s) trouvé(s)" + (f" (affichage des {limit} premiers)" if len(cands) > limit else "") + ":")
    out(f"{'#':>3}  {'Type':<22} {'Taille':>9}  {'En-tête':<8} Chemin")
    for i, c in enumerate(cands[:limit], 1):
        flag = "verrouillé" if c.locked else ("OK" if c.header_verified else "extension")
        out(f"{i:>3}  {c.kind:<22} {human(c.size):>9}  {flag:<8} {c.path}")


def choose(cands: list[Candidate], input_fn=input, out=print) -> str | None:
    """Returns the chosen path, or None if the operator quits."""
    while True:
        show(cands, out=out)
        a = input_fn("\nNuméro du fichier à utiliser, [m] saisir un chemin, [q] quitter : ").strip().lower()
        if a == "q": return None
        if a == "m":
            p = input_fn("Chemin complet : ").strip().strip('"')
            if os.path.isfile(p): return p
            out("Fichier introuvable."); continue
        if a.isdigit() and 1 <= int(a) <= min(len(cands), 60): 
            c = cands[int(a) - 1]
            if input_fn(f"Confirmer : {c.path} ? [o/N] ").strip().lower() in ("o", "oui", "y"): return c.path
            continue
        out("Choix invalide.")


def proceed(path: str, input_fn=input, out=print, run_scan=None) -> dict:
    """After the operator picked a file: fingerprint it, then offer the next safe step."""
    if os.path.splitext(path)[1].lower() in {".sql", ".dump", ".backup"}:
        out(
            "\nCe fichier est un dump/sauvegarde, pas une base directement interrogeable. "
            "L'agent ne l'exécute pas et ne l'envoie pas. Connectez-vous à une base active "
            "avec un compte en lecture seule, ou utilisez une base SQLite prise en charge."
        )
        return {"path": path, "fingerprint": None, "scanned": False}

    fp = fingerprint(Evidence(selected_files=[path]))
    out("\nEmpreinte du moteur (indices locaux, non définitifs) :")
    for c in fp["candidates"]: out(f"  - {c['engine']}  score {c['score']}  ({', '.join(c['evidence'])})")
    if not fp["candidates"]: out("  Aucun indice : moteur inconnu. Ne devinez pas ; confirmez-le avec l'éditeur/le client.")
    engine = fp["decision"]; res = {"path": path, "fingerprint": fp, "scanned": False}
    if engine == "sqlite":
        if input_fn("Fichier SQLite vérifié (ouverture strictement en lecture seule). Lancer l'extraction des métadonnées ? [o/N] ").strip().lower() in ("o", "oui", "y"):
            os.environ["UDME_DB_URL"] = wingest.build_url("sqlite", path=path.replace("\\", "/"))
            if run_scan: run_scan(); res["scanned"] = True
        return res
    out("\n" + LIVE_WARNING)
    if engine in wingest.URL_TEMPLATES:
        out(f"Moteur probable : {engine}. Pilote requis : {wingest.EXTRA_PACKAGES[engine]}")
        out(f"Modèle d'URL : {wingest.URL_TEMPLATES[engine]}")
        out("Définissez UDME_DB_URL avec un compte LECTURE SEULE, puis : udme-agent scan --confirm-read-only")
    else:
        out("Moteur à confirmer avant toute extraction (relancez avec --engine ou consultez l'éditeur).")
    return res

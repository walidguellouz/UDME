"""Deterministic business mapper (plan section 9). Rule-based first; an LLM
provider can be plugged in via `SemanticProvider` for ambiguous objects only.
Clue vocabulary = candidate-generation hints, NOT verified WinGest names."""
from __future__ import annotations
from typing import Protocol
from .model import Package, BusinessClassification
from .text import tokens

TAXONOMY: dict[str, dict] = {
    "catalog.product": {"t": ["art", "article", "prod", "produit", "medicament", "specialite"], "c": ["ean", "code", "tva", "designation", "libelle", "prix"]},
    "inventory.stock_balance": {"t": ["stk", "stock", "depot"], "c": ["qte", "quantite", "depot"]},
    "inventory.stock_movement": {"t": ["mvt", "mouvement", "movement"], "c": ["qte", "date", "lot"]},
    "inventory.batch": {"t": ["lot", "peremption"], "c": ["lot", "peremption", "expiry"]},
    "sales.sale": {"t": ["vte", "vente", "ticket", "fact", "facture"], "c": ["total", "date", "ttc", "montant"]},
    "sales.sale_line": {"t": ["lig", "ligne", "line", "detail"], "c": ["qte", "prix", "pu", "quantite"]},
    "sales.payment": {"t": ["reglement", "paiement", "payment", "caisse"], "c": ["mode", "montant"]},
    "procurement.purchase_order": {"t": ["achat", "cmd", "commande"], "c": ["date", "four", "frs"]},
    "procurement.goods_receipt": {"t": ["reception", "bl"], "c": ["date", "four"]},
    "procurement.supplier": {"t": ["four", "frs", "fournisseur", "supplier"], "c": ["nom", "adresse", "tel", "name"]},
    "customers.customer": {"t": ["client", "cli", "customer", "patient"], "c": ["nom", "adresse", "tel"]},
    "security.user": {"t": ["user", "util", "utilisateur", "role", "droit"], "c": ["login", "pwd", "password"]},
    "reference.tax": {"t": ["tva", "tax", "taxe"], "c": ["taux", "rate"]},
    "reference.family": {"t": ["famille", "family", "categorie", "unite"], "c": ["libelle"]},
}


class SemanticProvider(Protocol):
    def classify(self, ambiguous: list[dict]) -> list[BusinessClassification]: ...


def _match(tok: str, clue: str) -> float:
    if tok == clue: return 1.0
    if len(clue) >= 3 and (tok.startswith(clue) or tok.endswith(clue)): return 0.5
    return 0.0


def classify_tables(pkg: Package) -> list[BusinessClassification]:
    out = []
    for sname, t in pkg.iter_tables():
        if t.object_type != "table": continue
        ttoks = tokens(t.name)
        ctoks = {x for c in t.columns for x in tokens(c.name)}
        scores: dict[str, tuple[float, list[str]]] = {}
        for label, clues in TAXONOMY.items():
            ev, name_w = [], 0.0
            for tok in ttoks:
                for cl in clues["t"]:
                    w = _match(tok, cl)
                    if w:
                        name_w = max(name_w, w); ev.append(f"table_token:{tok}~{cl}")
            if not name_w: continue
            col_hits = [cl for cl in clues["c"] if any(_match(x, cl) >= 1.0 for x in ctoks)]
            ev += [f"column_token:{c}" for c in col_hits]
            score = 0.45 + 0.20 * name_w + min(0.04 * len(col_hits), 0.2)
            scores[label] = (round(min(score, 0.94), 2), ev)
        oid = f"{sname}.{t.name}"
        if not scores:
            out.append(BusinessClassification(object_id=oid, label="UNKNOWN", confidence=0.0, evidence=[]))
            continue
        ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
        best, (conf, ev) = ranked[0]
        if conf < 0.60:  # plan 9.4: below 0.60 => no definitive label
            out.append(BusinessClassification(object_id=oid, label="UNKNOWN", confidence=conf, evidence=ev,
                                              alternatives=[k for k, _ in ranked[:3]]))
        else:
            out.append(BusinessClassification(object_id=oid, label=best, confidence=conf, evidence=ev,
                                              alternatives=[k for k, _ in ranked[1:3]]))
    return out

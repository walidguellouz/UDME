"""Evidence-scored relationship inference (plan section 8).
Scores are ranking signals, not probabilities. Nothing but a declared FK is
ever auto-accepted."""
from __future__ import annotations
from .model import Package, RelationshipCandidate, Table
from .text import tokens, entity_tokens, GENERIC


def _keys(t: Table) -> list[tuple[list[str], str]]:
    """Single-column key candidates: PK, unique constraints, unique indexes."""
    out = []
    if len(t.primary_key) == 1: out.append((t.primary_key, "primary_key"))
    out += [(u, "unique_constraint") for u in t.unique_constraints if len(u) == 1]
    out += [(i.columns, "unique_index") for i in t.indexes if i.unique and len(i.columns) == 1]
    return out


def infer_relationships(pkg: Package, min_score: float = 0.60) -> list[RelationshipCandidate]:
    tables = {f"{s}.{t.name}": t for s, t in pkg.iter_tables() if t.object_type == "table"}
    found: dict[tuple, RelationshipCandidate] = {}
    declared_cols = set()

    for sname, a in tables.items():  # explicit FKs: highest confidence
        for fk in a.foreign_keys:
            sch = fk.ref_schema or sname.split(".")[0]
            tgt = f"{sch}.{fk.ref_table}"
            declared_cols.add((sname, tuple(fk.columns)))
            uniq = set(a.primary_key) == set(fk.columns)
            found[(sname, tuple(fk.columns), tgt, tuple(fk.ref_columns))] = RelationshipCandidate(
                source_table=sname, source_columns=fk.columns, target_table=tgt,
                target_columns=fk.ref_columns, candidate_type="one_to_one" if uniq else "one_to_many",
                score=1.0, evidence=["declared_foreign_key"], declared=True, status="accepted")

    for bname, b in tables.items():
        b_tokens = set(entity_tokens(b.name))
        for kcols, kkind in _keys(b):
            k = next((c for c in b.columns if c.name == kcols[0]), None)
            if k is None: continue
            ktok = tokens(k.name)
            for aname, a in tables.items():
                for c in a.columns:
                    if aname == bname and c.name == k.name: continue
                    if (aname, (c.name,)) in declared_cols: continue
                    if c.normalized_type != k.normalized_type or c.normalized_type == "unknown": continue
                    ctok = tokens(c.name)
                    ev, score = [], 0.0
                    if c.name.lower() == k.name.lower() and not (set(ktok) <= GENERIC and len(ktok) == 1):
                        ev, score = ["exact_key_name_match"], 0.90
                    elif set(ctok) == set(ktok) and len(ktok) > 1:
                        ev, score = ["key_name_token_match"], 0.85
                    else:
                        rest_c = [t for t in ctok if t not in ktok]
                        if set(ktok) <= set(ctok) and rest_c and set(rest_c) <= b_tokens:
                            ev, score = ["column_names_target_table", "key_token_match"], 0.80
                    if not ev: continue
                    ev += ["compatible_types", f"target_is_{kkind}"]
                    if kkind == "primary_key": score += 0.04
                    source_unique = c.name in a.primary_key and len(a.primary_key) == 1 or any(
                        u == [c.name] for u in a.unique_constraints)
                    ev.append("source_column_is_unique" if source_unique else "source_column_may_repeat")
                    if not source_unique: score += 0.02
                    score = round(min(score, 0.98), 2)
                    if score < min_score: continue
                    key = (aname, (c.name,), bname, (k.name,))
                    if key not in found or found[key].score < score:
                        found[key] = RelationshipCandidate(
                            source_table=aname, source_columns=[c.name], target_table=bname,
                            target_columns=[k.name], score=score, evidence=ev,
                            candidate_type="one_to_one" if source_unique else "one_to_many")
    return sorted(found.values(), key=lambda r: (-r.score, r.source_table))

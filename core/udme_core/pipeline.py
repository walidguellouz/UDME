from __future__ import annotations
from dataclasses import dataclass
from .model import Package, RelationshipCandidate, BusinessClassification
from .inference import infer_relationships
from .mapper import classify_tables
from .package import schema_hash


@dataclass
class Analysis:
    package: Package
    relationships: list[RelationshipCandidate]
    mappings: list[BusinessClassification]
    schema_hash: str


def analyze(pkg: Package) -> Analysis:
    return Analysis(pkg, infer_relationships(pkg), classify_tables(pkg), schema_hash(pkg))


def diff(old: Package, new: Package) -> dict:
    def idx(p): return {f"{s}.{t.name}": {c.name: c.native_type for c in t.columns} for s, t in p.iter_tables()}
    a, b = idx(old), idx(new)
    return {"tables_added": sorted(set(b) - set(a)), "tables_removed": sorted(set(a) - set(b)),
            "columns_changed": {t: {"added": sorted(set(b[t]) - set(a[t])), "removed": sorted(set(a[t]) - set(b[t])),
                                    "type_changed": sorted(c for c in set(a[t]) & set(b[t]) if a[t][c] != b[t][c])}
                                for t in set(a) & set(b) if a[t] != b[t]}}

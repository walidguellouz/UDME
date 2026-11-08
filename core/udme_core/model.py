"""Canonical, versioned metadata contract (plan section 7.2)."""
from __future__ import annotations
from datetime import datetime, timezone
from pydantic import BaseModel, Field

PACKAGE_VERSION = "1.0"


class Column(BaseModel):
    name: str
    ordinal: int
    native_type: str
    normalized_type: str = "unknown"  # integer|decimal|string|date|datetime|boolean|binary|json|unknown
    nullable: bool | None = None  # None = metadata missing (not the same as False)
    default: str | None = None
    is_identity: bool = False


class ForeignKey(BaseModel):
    name: str | None = None
    columns: list[str]
    ref_schema: str | None = None
    ref_table: str
    ref_columns: list[str]


class Index(BaseModel):
    name: str | None = None
    unique: bool = False
    columns: list[str]


class Table(BaseModel):
    name: str
    object_type: str = "table"  # table|view
    columns: list[Column] = []
    primary_key: list[str] = []
    foreign_keys: list[ForeignKey] = []
    unique_constraints: list[list[str]] = []
    indexes: list[Index] = []
    row_estimate: int | None = None


class Schema(BaseModel):
    name: str
    tables: list[Table] = []


class Source(BaseModel):
    product_hint: str | None = None
    engine: str
    engine_version: str | None = None
    connector: str
    scan_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata_only: bool = True
    warnings: list[str] = []


class Package(BaseModel):
    package_version: str = PACKAGE_VERSION
    source: Source
    schemas: list[Schema] = []

    def iter_tables(self):
        for s in self.schemas:
            for t in s.tables:
                yield s.name, t


class RelationshipCandidate(BaseModel):
    source_table: str  # "schema.table"
    source_columns: list[str]
    target_table: str
    target_columns: list[str]
    candidate_type: str  # one_to_one|one_to_many
    score: float
    evidence: list[str]
    declared: bool = False
    status: str = "needs_review"  # needs_review|accepted (declared FK only)


class BusinessClassification(BaseModel):
    object_id: str
    label: str  # e.g. "sales.sale" or "UNKNOWN"
    confidence: float
    evidence: list[str]
    alternatives: list[str] = []
    review_required: bool = True

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol
from ..model import Package


@dataclass
class ReadOnlyReport:
    verified: bool
    method: str
    notes: list[str] = field(default_factory=list)


class DatabaseConnector(Protocol):
    engine_name: str

    def validate_connection(self) -> str: ...
    def verify_read_only(self) -> ReadOnlyReport: ...
    def extract(self, product_hint: str | None = None) -> Package: ...
    def close(self) -> None: ...

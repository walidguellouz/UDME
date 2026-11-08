"""Generic metadata-only connector built on SQLAlchemy's Inspector.

Safety contract (plan 6.4): only catalog reflection is executed (no arbitrary
SQL, no DDL/DML), read-only session where the engine supports it, and
fail-closed when read-only cannot be established unless the operator
explicitly confirms the account is read-only.
"""
from __future__ import annotations
from sqlalchemy import create_engine, inspect, types as sat, text
from sqlalchemy.engine import Engine, make_url
from .base import ReadOnlyReport
from .. import model as m


def normalize_type(t) -> str:
    if isinstance(t, sat.Boolean): return "boolean"
    if isinstance(t, sat.Integer): return "integer"
    if isinstance(t, (sat.Numeric, sat.Float)): return "decimal"
    if isinstance(t, sat.DateTime): return "datetime"
    if isinstance(t, sat.Date): return "date"
    if isinstance(t, (sat.String, sat.Text, sat.Enum)): return "string"
    if isinstance(t, sat.LargeBinary): return "binary"
    if isinstance(t, sat.JSON): return "json"
    return "unknown"  # never silently coerce


class SQLAlchemyConnector:
    def __init__(self, url: str, *, confirm_read_only_account: bool = False,
                 statement_timeout_s: int = 30, max_tables: int = 5000):
        u = make_url(url)
        self.engine_name = u.get_backend_name()
        self.confirm_ro = confirm_read_only_account
        self.max_tables = max_tables
        connect_args: dict = {}
        if self.engine_name == "sqlite" and u.database and u.database != ":memory:":
            url = f"sqlite:///file:{u.database}?mode=ro&uri=true"  # strictly read-only
            connect_args = {"timeout": statement_timeout_s}
        elif self.engine_name == "postgresql":
            connect_args = {"options": f"-c default_transaction_read_only=on "
                                       f"-c statement_timeout={statement_timeout_s * 1000}"}
        self.engine: Engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    def validate_connection(self) -> str:
        with self.engine.connect() as c:
            c.execute(text("SELECT 1"))
        return self.engine_name

    def verify_read_only(self) -> ReadOnlyReport:
        if self.engine_name == "sqlite":
            return ReadOnlyReport(True, "sqlite mode=ro (file opened read-only)")
        if self.engine_name == "postgresql":
            with self.engine.connect() as c:
                v = c.execute(text("SHOW transaction_read_only")).scalar()
            ok = str(v).lower() == "on"
            return ReadOnlyReport(ok, "session transaction_read_only", [] if ok else ["session is not read-only"])
        if self.confirm_ro:
            return ReadOnlyReport(True, "operator-confirmed read-only account",
                                  ["Not enforceable by the driver; relies on database permissions."])
        return ReadOnlyReport(False, "none", ["Read-only cannot be verified for this engine. "
                              "Use a read-only account and pass --confirm-read-only."])

    def extract(self, product_hint: str | None = None) -> m.Package:
        ro = self.verify_read_only()
        if not ro.verified:  # fail closed
            raise PermissionError("READ_ONLY_NOT_CONFIRMED: " + "; ".join(ro.notes))
        insp = inspect(self.engine)
        warnings: list[str] = list(ro.notes)
        try:
            version = ".".join(map(str, self.engine.dialect.server_version_info or ())) or None
        except Exception:
            version = None
        default_schema = insp.default_schema_name
        out: list[m.Schema] = []
        count = 0
        for sch in insp.get_schema_names() or [None]:
            if sch and sch.lower() in {"information_schema", "pg_catalog", "sys"}:
                continue
            tables = []
            names = [(n, "table") for n in insp.get_table_names(schema=sch)]
            try:
                names += [(n, "view") for n in insp.get_view_names(schema=sch)]
            except Exception as e:
                warnings.append(f"views not listed for {sch}: {type(e).__name__}")
            for name, kind in names:
                count += 1
                if count > self.max_tables:
                    warnings.append("max_tables reached; scan is partial")
                    break
                tables.append(self._table(insp, sch, name, kind, warnings))
            out.append(m.Schema(name=sch or default_schema or "main", tables=tables))
        return m.Package(source=m.Source(product_hint=product_hint, engine=self.engine_name,
                         engine_version=version, connector="sqlalchemy-generic/0.1", warnings=warnings),
                         schemas=out)

    def _table(self, insp, sch, name, kind, warnings) -> m.Table:
        cols = []
        try:
            for i, c in enumerate(insp.get_columns(name, schema=sch), 1):
                cols.append(m.Column(
                    name=c["name"], ordinal=i, native_type=str(c["type"]),
                    normalized_type=normalize_type(c["type"]), nullable=c.get("nullable"),
                    default=None if c.get("default") is None else str(c["default"]),
                    is_identity=bool(c.get("autoincrement") is True or c.get("identity"))))
        except Exception as e:
            warnings.append(f"columns unavailable for {name}: {type(e).__name__}")
        t = m.Table(name=name, object_type=kind, columns=cols)
        if kind == "view":
            return t
        try:
            t.primary_key = list(insp.get_pk_constraint(name, schema=sch).get("constrained_columns") or [])
            t.foreign_keys = [m.ForeignKey(name=f.get("name"), columns=f["constrained_columns"],
                              ref_schema=f.get("referred_schema"), ref_table=f["referred_table"],
                              ref_columns=f["referred_columns"]) for f in insp.get_foreign_keys(name, schema=sch)]
            t.unique_constraints = [list(u["column_names"]) for u in insp.get_unique_constraints(name, schema=sch)]
            t.indexes = [m.Index(name=i.get("name"), unique=bool(i.get("unique")),
                         columns=[c for c in i["column_names"] if c]) for i in insp.get_indexes(name, schema=sch)]
        except Exception as e:
            warnings.append(f"constraints incomplete for {name}: {type(e).__name__}")
        return t

    def close(self) -> None:
        self.engine.dispose()

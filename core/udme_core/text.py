import re, unicodedata

GENERIC = {"id", "code", "num", "ref", "no", "numero", "key", "cle"}
PREFIXES = {"t", "tbl", "tb", "tab"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokens(name: str) -> list[str]:
    """Split on underscores, camelCase and digits; lowercase; strip accents."""
    s = strip_accents(name)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+|(?<=\D)(?=\d)", s) if t]


def entity_tokens(table_name: str) -> list[str]:
    t = tokens(table_name)
    return [x for x in t if x not in PREFIXES] or t

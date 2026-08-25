"""Domain vocabulary used to normalize field names into comparable concepts.

Two lookup tables, both general-purpose:

`ABBREVIATIONS` expands the short forms that relational schemas conventionally
use (`cd` -> code, `nm` -> name, `dt` -> date). Keys are tokens, not field
names, so an entry helps every field that contains the token.

`ALIAS_GROUPS` collapses synonyms onto a single canonical concept, so that
`hire` and `start` compare equal. Groups are conceptual, not directional -- they
encode "these words mean the same thing", never "this column maps to that path".

Deliberately absent: any entry keyed on a specific source column or destination
path. If a mapping only works because of a hand-written pair, the generator
would be memorizing the answer rather than deriving it.
"""

from __future__ import annotations

# Token -> the tokens it expands to.
ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    "addr": ("address",),
    "amt": ("amount",),
    "cd": ("code",),
    "cnt": ("count",),
    "ctr": ("center",),
    "curr": ("currency",),
    "desc": ("description",),
    "dept": ("department",),
    "dob": ("date", "birth"),
    "dt": ("date",),
    "emp": ("employee",),
    "f": ("first",),
    "l": ("last",),
    "lvl": ("level",),
    "mgr": ("manager",),
    "nm": ("name",),
    "num": ("number",),
    "org": ("organization",),
    "ph": ("phone",),
    "prov": ("province",),
    "qty": ("quantity",),
    "rec": ("record",),
    "sal": ("salary",),
    "stat": ("status",),
    "tel": ("telephone",),
    "loc": ("location",),
    "ts": ("timestamp",),
    "tz": ("timezone",),
}

# Canonical concept -> the surface words that mean it.
ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "status": ("status", "active", "inactive", "flag", "enabled", "disabled"),
    "start": ("start", "hire", "hired", "begin", "join", "joined", "onboard"),
    "end": ("end", "term", "terminate", "terminated", "termination", "exit", "offboard"),
    "manager": ("manager", "supervisor"),
    "salary": ("salary", "compensation", "pay", "wage", "remuneration"),
    "create": ("create", "created", "creation", "inserted"),
    "update": ("update", "updated", "modified", "changed"),
    "name": ("name", "title", "label"),
    "phone": ("phone", "telephone", "mobile"),
    "email": ("email", "mail"),
    "level": ("level", "grade", "band", "tier", "rank"),
    "country": ("country", "nation"),
    "postal": ("postal", "zip"),
    "timezone": ("timezone", "tz"),
    "person": ("employee", "person", "staff", "worker", "personnel"),
    "timestamp": ("timestamp", "datetime"),
}

# Structural filler that carries no matching signal on either side
# (`isActive`, `createdAt`, `stateOrProvince`).
STOPWORDS: frozenset[str] = frozenset(
    {"is", "has", "or", "and", "at", "of", "the", "a", "an", "to", "by", "in", "on"}
)

# Reverse index: surface word -> canonical concept.
_CANONICAL: dict[str, str] = {
    word: canonical
    for canonical, words in ALIAS_GROUPS.items()
    for word in words
}


def canonicalize(token: str) -> str:
    """Fold a token onto its alias group, if it belongs to one."""
    return _CANONICAL.get(token, token)

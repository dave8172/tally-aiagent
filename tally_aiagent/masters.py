"""Tally's own master list, and the resolver that is this library's whole point.

Read this if you read nothing else:

    Tally does not reject a master name it has never seen. It creates one.

Send a purchase voucher naming "ACME SUPPLIES CO. LTD" to a Tally that holds
"ACME SUPPLIES CO LTD" and Tally will not error. It will quietly open a second
supplier ledger, post the bill against it, and return CREATED=1. Every report
downstream is now wrong in a way nothing flags, and you find out weeks later
when someone reconciles a statement.

So the rule enforced here is: **every master name written into a voucher must
come out of Tally's own export, never out of your database.** Your system
supplies quantities, rates, dates and references. Tally supplies names.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .xml_util import attr, blocks, tag


def normalize(text: str) -> str:
    """Punctuation- and space-insensitive comparison key.

    Used ONLY to *find* the Tally name. The Tally spelling is what gets written —
    this key never reaches a voucher.
    """
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


@dataclass
class Masters:
    """Canonical names exactly as Tally holds them.

    `items` maps stock item name -> {guid, parent, hsn, units}
    `ledgers` maps ledger name -> {guid, parent}
    """

    items: dict[str, dict] = field(default_factory=dict)
    ledgers: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        self._item_index: dict[str, list[str]] = {}
        self._ledger_index: dict[str, list[str]] = {}
        self._item_count = -1
        self._ledger_count = -1

    def _items_index(self) -> dict[str, list[str]]:
        """Rebuilt whenever the table changes size.

        Callers legitimately populate `items` and `ledgers` directly — a test
        fixture, a cached master list loaded from elsewhere — and an index built
        once at construction would silently match nothing for them. Failing to
        resolve is the one failure mode this class must never have.
        """
        if self._item_count != len(self.items):
            self._item_index = _build_index(self.items)
            self._item_count = len(self.items)
        return self._item_index

    def _ledgers_index(self) -> dict[str, list[str]]:
        if self._ledger_count != len(self.ledgers):
            self._ledger_index = _build_index(self.ledgers)
            self._ledger_count = len(self.ledgers)
        return self._ledger_index

    def reindex(self) -> None:
        """Force an index rebuild after renaming a master in place."""
        self._item_count = self._ledger_count = -1

    def resolve_item(self, name: str) -> tuple[str | None, str]:
        """Resolve a stock item name. Returns (tally_name_or_None, explanation)."""
        return _resolve(name, self.items, self._items_index(), "stock item")

    def resolve_ledger(self, name: str) -> tuple[str | None, str]:
        """Resolve a ledger name. Returns (tally_name_or_None, explanation)."""
        return _resolve(name, self.ledgers, self._ledgers_index(), "ledger")

    def units_for(self, item_name: str, default: str = "Nos") -> str:
        """Base unit Tally holds for an item, so quantities are not guessed."""
        return (self.items.get(item_name) or {}).get("units") or default

    def candidates(self, name: str, kind: str = "item", limit: int = 10) -> list[str]:
        """Names that look like `name`, for showing a human when the gate refuses.

        Suggests; never chooses. Picking one of these automatically is exactly
        the failure this library exists to prevent.

        Substring matching alone is not enough here, and the reason is the whole
        point of the library: the dangerous near-miss is a name where one *word*
        differs — "Acme Supplies Co Ltd" against "Acme Supplies Pvt Ltd" — and
        neither string contains the other. So this also does a fuzzy pass, or
        the suggestion would be empty in precisely the case that matters most.
        """
        table = self.items if kind == "item" else self.ledgers
        key = normalize(name)
        if not key:
            return []

        scored: dict[str, float] = {}
        for candidate in table:
            other = normalize(candidate)
            if not other:
                continue
            if key in other or other in key:
                # A containment hit is strong; rank shorter differences first.
                scored[candidate] = 1.0 - min(abs(len(other) - len(key)), 40) / 1000
            else:
                ratio = SequenceMatcher(None, key, other).ratio()
                if ratio >= 0.6:
                    scored[candidate] = ratio

        return [name for name, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]

    def __repr__(self) -> str:
        return f"<Masters items={len(self.items)} ledgers={len(self.ledgers)}>"


def _build_index(table: dict) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for name in table:
        index.setdefault(normalize(name), []).append(name)
    return index


def _resolve(query, table, index, kind) -> tuple[str | None, str]:
    """Exact match wins. Otherwise a *unique* normalized match.

    Ambiguity is treated as failure. If "PSU-500" normalizes the same as both
    "PSU 500H" and "PSU 500S", there is no safe answer and guessing books the
    wrong item against a real supplier with nothing downstream able to detect it.
    """
    text = (query or "").strip()
    if not text:
        return None, f"empty {kind} name"
    if text in table:
        return text, "exact"
    hits = index.get(normalize(text), [])
    if len(hits) == 1:
        return hits[0], f"normalized ({text!r} -> {hits[0]!r})"
    if len(hits) > 1:
        return None, (
            f"ambiguous — {len(hits)} {kind}s in Tally normalize alike: {hits}. "
            "Name the exact one."
        )
    return None, f"no {kind} in Tally matches {text!r}"


def fetch_masters(tally) -> Masters:
    """Pull stock items and ledgers out of Tally.

    HSN lives on the stock GROUP and is inherited by items, so groups are read
    first and folded in — an item-level HSN lookup alone comes back empty and
    looks like missing data.
    """
    masters = Masters()

    raw = tally.export("List of Accounts", "<ACCOUNTTYPE>Stock Items</ACCOUNTTYPE>")
    group_hsn: dict[str, str] = {}
    for block in blocks(raw, "STOCKGROUP"):
        name = attr(block, "STOCKGROUP", "NAME")
        hsn = re.search(r"<HSNCODE>\s*(\d+)\s*</HSNCODE>", block)
        if name and hsn:
            group_hsn[name] = hsn.group(1)

    for block in blocks(raw, "STOCKITEM"):
        name = attr(block, "STOCKITEM", "NAME")
        if not name or tag(block, "ISDELETED") == "Yes":
            continue
        parent = tag(block, "PARENT") or ""
        own_hsn = re.search(r"<HSNCODE>\s*(\d+)\s*</HSNCODE>", block)
        masters.items[name] = {
            "guid": tag(block, "GUID"),
            "parent": parent,
            "hsn": own_hsn.group(1) if own_hsn else group_hsn.get(parent),
            "units": tag(block, "BASEUNITS") or "Nos",
        }

    raw = tally.export("List of Accounts", "<ACCOUNTTYPE>Ledgers</ACCOUNTTYPE>")
    for block in blocks(raw, "LEDGER"):
        name = attr(block, "LEDGER", "NAME")
        if not name or tag(block, "ISDELETED") == "Yes":
            continue
        masters.ledgers[name] = {
            "guid": tag(block, "GUID"),
            "parent": tag(block, "PARENT") or "",
        }

    return masters

"""Closing stock quantities.

Tally omits items with zero or negative stock from a Stock Summary export, so
an item missing from the response means zero — not "unchanged". Anything
mirroring this into its own table must zero the absentees explicitly or stock
that has run out will read as still in hand.
"""
import re

from .xml_util import tag


def stock_summary(tally) -> dict[str, float]:
    """Return {item_name: closing_qty} for every item Tally reports."""
    raw = tally.export(
        "Stock Summary",
        "<ISITEMWISE>Yes</ISITEMWISE><EXPLODEITEMS>Yes</EXPLODEITEMS>",
    )
    names = re.findall(r"<DSPDISPNAME>([^<]+)</DSPDISPNAME>", raw)
    quantities = re.findall(r"<DSPCLQTY>([^<]*)</DSPCLQTY>", raw)

    result: dict[str, float] = {}
    for name, quantity in zip(names, quantities):
        quantity = quantity.strip()
        try:
            value = float(quantity.split()[0]) if quantity else 0.0
        except (ValueError, IndexError):
            value = 0.0
        result[name.strip()] = value
    return result


def item_balance(tally, item_name: str) -> float | None:
    """Closing quantity for one item, or None if Tally does not report it."""
    return stock_summary(tally).get(item_name)


def bills_outstanding(tally, ledger_name: str) -> list[dict]:
    """Open bills against one party ledger."""
    raw = tally.export(
        "Ledger Outstandings",
        f"<LEDGERNAME>{ledger_name}</LEDGERNAME>",
    )
    bills = []
    for block in re.findall(r"<BILLFIXED>(.*?)</BILLFIXED>", raw, re.S):
        bills.append(
            {
                "bill": tag(block, "BILLREF") or tag(block, "NAME"),
                "date": tag(block, "BILLDATE"),
                "amount": tag(block, "AMOUNT") or tag(block, "CLOSINGBALANCE"),
            }
        )
    return bills

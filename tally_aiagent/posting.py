"""The gate, the write, and the read-back check.

The flow is deliberately not collapsible into one call:

    preparation = tally.prepare(voucher)   # resolves names, prices, sends NOTHING
    print(preparation.report)              # a human or an agent looks
    result = tally.post(preparation)       # writes, then reads back and compares

You cannot post something that was not prepared. That is not a style
preference — it is the approval gate expressed as a type, so that skipping the
review step requires deleting code rather than forgetting a flag.
"""
import re
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal

from .errors import GateError, NotPrepared, Unreachable, VerificationError
from .money import exact, money
from .xml_util import blocks, tag


@dataclass
class Preparation:
    """A gated, priced voucher and the report of how every name resolved.

    Nothing has been sent to Tally at this point. `xml` is the exact body that
    will be sent, credentials excluded.
    """

    voucher: object
    report: list[str] = field(default_factory=list)
    xml: str = ""

    @property
    def totals(self) -> dict:
        v = self.voucher
        return {
            "goods": v.goods,
            "charges": v.charges_total,
            "round_off": v.round_off,
            "party_total": v.party_total,
        }

    def as_text(self) -> str:
        return "\n".join(self.report)

    def __str__(self) -> str:
        return self.as_text()


def prepare(tally, voucher, masters=None) -> Preparation:
    """Resolve every name against Tally, compute the money, refuse on any doubt.

    Masters are re-read from Tally by default even if they were cached, because
    somebody may have renamed a ledger since the last look and the whole point
    is that the names written are the names Tally holds *now*.

    Raises GateError listing every problem at once — a voucher is all-or-nothing,
    so reporting only the first failure would mean fixing them one round trip at
    a time.
    """
    masters = masters if masters is not None else tally.masters(refresh=True)
    report: list[str] = []
    problems: list[str] = []

    if voucher.kind == "journal":
        _prepare_journal(voucher, masters, report, problems)
    else:
        _prepare_invoice(voucher, masters, report, problems)

    if problems:
        raise GateError(
            "Refusing to post — these names could not be sourced from Tally:\n  - "
            + "\n  - ".join(problems)
            + "\n\nTally would not reject these. It would create them, silently, "
            "and return success. Create or correct the master in Tally first, "
            "then post."
        )

    voucher.prepared = True
    return Preparation(voucher=voucher, report=report, xml=voucher.body())


def _prepare_invoice(voucher, masters, report, problems):
    name, how = masters.resolve_ledger(voucher.party)
    if not name:
        problems.append(f"party {voucher.party!r}: {how}{_hint(masters, voucher.party, 'ledger')}")
    else:
        voucher.tally_party = name
        report.append(f"party    {voucher.party!r} -> {name!r}  [{how}]")

    name, how = masters.resolve_ledger(voucher.item_ledger)
    if not name:
        problems.append(
            f"item ledger {voucher.item_ledger!r}: {how}"
            f"{_hint(masters, voucher.item_ledger, 'ledger')}"
        )
    else:
        voucher.tally_item_ledger = name
        report.append(f"ledger   {voucher.item_ledger!r} -> {name!r}  [{how}]")

    if not voucher.lines:
        problems.append("voucher has no inventory lines")

    total = Decimal("0.00")
    for line in voucher.lines:
        item, how = masters.resolve_item(line.item)
        if not item:
            problems.append(f"item {line.item!r}: {how}{_hint(masters, line.item, 'item')}")
            continue
        try:
            rate, amount = line.compute()
        except ValueError as exc:
            problems.append(str(exc))
            continue
        line.tally_item = item
        line.resolved_rate = rate
        line.amount = amount
        line.resolved_unit = line.unit or masters.units_for(item)
        total += amount
        report.append(
            f"item     {line.item!r} -> {item!r}  [{how}]  "
            f"{line.qty} x {rate} = {amount}"
        )

    charges_total = Decimal("0.00")
    for charge in voucher.charges:
        name, how = masters.resolve_ledger(charge.ledger)
        if not name:
            problems.append(
                f"charge ledger {charge.ledger!r}: {how}"
                f"{_hint(masters, charge.ledger, 'ledger')}"
            )
            continue
        charge.tally_ledger = name
        charges_total += money(charge.amount)
        report.append(f"charge   {charge.ledger!r} -> {name!r}  [{how}]  {money(charge.amount)}")

    if voucher.round_off_ledger:
        name, how = masters.resolve_ledger(voucher.round_off_ledger)
        if not name:
            problems.append(f"round-off ledger {voucher.round_off_ledger!r}: {how}")
        else:
            voucher.round_off_ledger = name

    voucher.goods = money(total)
    voucher.charges_total = money(charges_total)
    computed = money(voucher.goods + voucher.charges_total)

    if voucher.invoice_total is not None:
        if not voucher.round_off_ledger:
            problems.append(
                "invoice_total was given without round_off_ledger — there is "
                "nowhere to book the difference."
            )
        voucher.round_off = money(exact(voucher.invoice_total) - computed)
        voucher.party_total = money(voucher.invoice_total)
    else:
        voucher.round_off = Decimal("0.00")
        voucher.party_total = computed

    report.append(
        f"totals   goods={voucher.goods}  charges={voucher.charges_total}  "
        f"round_off={voucher.round_off}  party={voucher.party_total}"
    )


def _prepare_journal(voucher, masters, report, problems):
    if not voucher.entries:
        problems.append("journal voucher has no entries")

    debits = credits = Decimal("0.00")
    for entry in voucher.entries:
        name, how = masters.resolve_ledger(entry.ledger)
        if not name:
            problems.append(f"ledger {entry.ledger!r}: {how}{_hint(masters, entry.ledger, 'ledger')}")
            continue
        entry.tally_ledger = name
        amount = money(entry.amount)
        if entry.side == "debit":
            debits += amount
        else:
            credits += amount
        report.append(f"{entry.side:<8} {entry.ledger!r} -> {name!r}  [{how}]  {amount}")

    if not problems and money(debits) != money(credits):
        problems.append(
            f"journal does not balance: debits {money(debits)} != credits {money(credits)}"
        )
    voucher.goods = money(debits)
    voucher.party_total = money(debits)
    report.append(f"totals   debits={money(debits)}  credits={money(credits)}")


def _hint(masters, name, kind) -> str:
    """Offer lookalikes so a human can fix it. Never auto-selects one."""
    candidates = masters.candidates(name, kind="item" if kind == "item" else "ledger")
    if not candidates:
        return ""
    shown = ", ".join(repr(c) for c in candidates[:5])
    return f"\n      did you mean: {shown}"


# ------------------------------------------------------------------- writing


def post(tally, preparation, verify: str = "warn") -> dict:
    """Send a prepared voucher, then read it back out of Tally and compare.

    verify:
        "warn"   (default) read back, return the differences in the result
        "strict" read back, raise VerificationError on any difference
        "off"    do not read back — you are trusting CREATED=1, which is not proof

    Returns a dict with Tally's own counters, the voucher GUID, and
    `differences` — an empty list means Tally stored exactly what was intended.
    """
    if not isinstance(preparation, Preparation):
        raise NotPrepared(
            "post() takes the object returned by prepare(), not a raw voucher. "
            "This is what stops an unreviewed write."
        )
    voucher = preparation.voucher
    raw = tally.import_data(preparation.xml)
    result = _parse_import_result(raw)

    if result.get("errors") or result.get("exceptions") or result.get("lineerrors"):
        result["differences"] = ["Tally reported errors on import — see lineerrors."]
        result["posted"] = False
        return result

    result["posted"] = bool(result.get("created"))

    if verify == "off" or not result["posted"]:
        result["differences"] = []
        return result

    try:
        actual = read_voucher(tally, voucher.voucher_number, voucher.voucher_type, voucher.date)
        if actual is None and result.get("lastmid"):
            # The voucher type is auto-numbered: Tally ignored the number we sent
            # and used its own. Find it by the id Tally reported instead.
            actual = read_voucher_by_master_id(
                tally, result["lastmid"], voucher.voucher_type, voucher.date
            )
            if actual is not None:
                result["assigned_voucher_number"] = actual["voucher_number"]
    except Unreachable as exc:
        result["differences"] = [f"Could not read the voucher back: {exc}"]
        return result

    differences = compare(voucher, actual)
    result["differences"] = differences
    result["read_back"] = actual
    if actual:
        result["guid"] = actual.get("guid")

    if differences and verify == "strict":
        raise VerificationError(
            "Voucher was written but does not match what was sent:\n  - "
            + "\n  - ".join(differences)
            + "\n\nThe voucher EXISTS in Tally. Nothing has been rolled back.",
            differences=differences,
            voucher_number=voucher.voucher_number,
        )
    return result


def _parse_import_result(raw: str) -> dict:
    result = {
        key.lower(): int(value)
        for key, value in re.findall(
            r"<(CREATED|ALTERED|DELETED|IGNORED|ERRORS|EXCEPTIONS|CANCELLED|LASTVCHID|LASTMID)>"
            r"\s*(-?\d+)\s*</\1>",
            raw,
        )
    }
    line_errors = re.findall(r"<LINEERROR>([^<]*)</LINEERROR>", raw)
    if line_errors:
        from html import unescape

        result["lineerrors"] = [unescape(e).strip() for e in line_errors]
    return result


# ------------------------------------------------------------------- reading


def read_voucher(tally, voucher_number: str, voucher_type: str, on_date: str) -> dict | None:
    """Read one voucher back out of Tally and re-total it from what Tally stored.

    This is the ground truth. CREATED=1 says Tally accepted an envelope; it does
    not say the voucher holds the numbers you meant.
    """
    start, end = _financial_year(on_date)
    raw = tally.export(
        "Voucher Register",
        f'<SVFROMDATE TYPE="Date">{start}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{end}</SVTODATE>'
        f"<VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>",
    )
    for block in blocks(raw, "VOUCHER"):
        if (tag(block, "VOUCHERNUMBER") or "") != voucher_number:
            continue
        return _parse_voucher(block, voucher_number)
    return None


def read_voucher_by_master_id(tally, master_id, voucher_type: str, on_date: str) -> dict | None:
    """Read a voucher back by Tally's internal MASTERID.

    Needed because many voucher types are **auto-numbered**: Tally ignores the
    number you send and assigns its own from the type's sequence. Reading back
    by the number you sent then finds nothing, even though the voucher posted
    perfectly well. Tally returns the id it used as LASTMID on the import.
    """
    start, end = _financial_year(on_date)
    raw = tally.export(
        "Voucher Register",
        f'<SVFROMDATE TYPE="Date">{start}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{end}</SVTODATE>'
        f"<VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>",
    )
    for block in blocks(raw, "VOUCHER"):
        if (tag(block, "MASTERID") or "") == str(master_id):
            return _parse_voucher(block, tag(block, "VOUCHERNUMBER") or "")
    return None


def _parse_voucher(block: str, voucher_number: str) -> dict:
    lines, goods = [], Decimal("0.00")
    for entry in re.findall(
        r"<ALLINVENTORYENTRIES\.LIST>(.*?)</ALLINVENTORYENTRIES\.LIST>", block, re.S
    ):
        amount = Decimal(tag(entry, "AMOUNT") or "0")
        goods += amount
        lines.append(
            {
                "item": tag(entry, "STOCKITEMNAME"),
                "qty": (tag(entry, "ACTUALQTY") or "").strip(),
                "rate": (tag(entry, "RATE") or "").split("/")[0],
                "amount": abs(amount),
            }
        )
    stripped = re.sub(
        r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", block, flags=re.S
    )
    party_amount = Decimal("0.00")
    ledgers = []
    for entry in re.findall(r"<LEDGERENTRIES\.LIST>(.*?)</LEDGERENTRIES\.LIST>", stripped, re.S):
        name = tag(entry, "LEDGERNAME")
        amount = Decimal(tag(entry, "AMOUNT") or "0")
        if tag(entry, "ISPARTYLEDGER") == "Yes":
            party_amount = amount
        ledgers.append({"ledger": name, "amount": amount})
    return {
        "guid": tag(block, "GUID"),
        "masterid": tag(block, "MASTERID"),
        "voucher_number": voucher_number,
        "date": tag(block, "DATE"),
        "party": tag(block, "PARTYLEDGERNAME"),
        "reference": tag(block, "REFERENCE"),
        "goods": abs(goods),
        "party_total": abs(party_amount),
        "lines": lines,
        "ledgers": ledgers,
    }


def compare(voucher, actual: dict | None) -> list[str]:
    """Intended vs stored. An empty list means they agree.

    The voucher NUMBER is deliberately not compared: on an auto-numbered type
    Tally assigns its own, and that is correct behaviour rather than drift.
    Everything that carries money or identity is compared.
    """
    if actual is None:
        return ["Voucher was not found in Tally when reading it back."]
    differences = []
    if voucher.kind != "journal":
        if money(voucher.goods) != money(actual["goods"]):
            differences.append(
                f"goods: sent {money(voucher.goods)}, Tally has {money(actual['goods'])}"
            )
        if money(voucher.party_total) != money(actual["party_total"]):
            differences.append(
                f"party total: sent {money(voucher.party_total)}, "
                f"Tally has {money(actual['party_total'])}"
            )
        if len(actual["lines"]) != len(voucher.lines):
            differences.append(
                f"line count: sent {len(voucher.lines)}, Tally has {len(actual['lines'])}"
            )
        if (actual.get("party") or "") != (voucher.tally_party or ""):
            differences.append(
                f"party: sent {voucher.tally_party!r}, Tally has {actual.get('party')!r}"
            )
    return differences


def next_voucher_number(tally, prefix: str, voucher_type: str, on_date: str | None = None):
    """Suggest the next free voucher number by reading the live maximum.

    Returns (suggested, warning_or_None). It is a SUGGESTION, not a reservation:
    a colleague may be entering vouchers in Tally at the same moment, so keep it
    editable. Tally rejects a true duplicate at post time.

    Only meaningful for voucher types set to manual numbering.
    """
    on_date = on_date or _date.today().strftime("%Y%m%d")
    start, end = _financial_year(on_date)
    suffix = f"{start[2:4]}{end[2:4]}"
    try:
        raw = tally.export(
            "Voucher Register",
            f'<SVFROMDATE TYPE="Date">{start}</SVFROMDATE>'
            f'<SVTODATE TYPE="Date">{end}</SVTODATE>'
            f"<VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>",
        )
    except Unreachable as exc:
        return f"{prefix}-001/{suffix}", f"Could not read Tally ({exc}). Check the number."

    numbers = [
        int(n)
        for n in re.findall(
            rf"<VOUCHERNUMBER>\s*{re.escape(prefix)}-(\d+)/{suffix}\s*</VOUCHERNUMBER>", raw
        )
    ]
    if not numbers:
        return f"{prefix}-001/{suffix}", f"No {prefix}-nnn/{suffix} vouchers in Tally yet."
    gaps = sorted(set(range(1, max(numbers))) - set(numbers))
    warning = (
        f"Gaps in the {prefix} sequence: {', '.join(f'{g:03d}' for g in gaps[:10])}"
        if gaps
        else None
    )
    return f"{prefix}-{max(numbers) + 1:03d}/{suffix}", warning


def _financial_year(on_date: str) -> tuple[str, str]:
    """Indian financial year (1 April - 31 March) containing YYYYMMDD."""
    year, month = int(on_date[:4]), int(on_date[4:6])
    start_year = year if month >= 4 else year - 1
    return f"{start_year}0401", f"{start_year + 1}0331"

"""Voucher shapes.

Sign convention, which Tally documents nowhere obvious and which is the source
of most import bugs:

    negative AMOUNT = debit        positive AMOUNT = credit

A purchase debits the goods and credits the supplier. A sale credits the goods
and debits the customer. A journal must sum to zero.

MATURITY — read before using this in anger:

    purchase()  Verified against real vouchers, to the paisa, in daily use.
    sales()     Follows the documented shape. NOT verified against a real
                Tally sales voucher. Post one to a test company first.
    journal()   Follows the documented shape. NOT verified against a real
                Tally journal voucher. Post one to a test company first.

The gate and the read-back verification apply identically to all three, which
is what makes trying the unverified ones survivable: prepare() will refuse
unknown names, and post(verify=...) reads the voucher back and tells you
whether Tally stored what you meant.
"""
import warnings
from dataclasses import dataclass, field
from decimal import Decimal

from .money import exact, money
from .xml_util import esc

UNVERIFIED = (
    "{kind}() has not been verified against a real Tally voucher. "
    "Post to a test company first and check the read-back report. "
    "See the MATURITY note in tally_aiagent/vouchers.py."
)


@dataclass
class Line:
    """One inventory line.

    Give either `rate` (already in the company's base currency) or
    `unit_cost` + `currency_rate` for a foreign-currency purchase.

    `item` is whatever your system calls it. The gate resolves it against
    Tally's master list and writes Tally's spelling, not yours.
    """

    item: str
    qty: Decimal | int | str
    rate: Decimal | int | str | None = None
    unit_cost: Decimal | int | str | None = None
    currency_rate: Decimal | int | str | None = None
    unit: str | None = None

    # filled in by prepare()
    tally_item: str | None = None
    resolved_rate: Decimal | None = None
    amount: Decimal | None = None
    resolved_unit: str | None = None

    def compute(self) -> tuple[Decimal, Decimal]:
        """Return (rate, amount). Rate is rounded before multiplying — see money.py."""
        if self.rate is not None:
            rate = money(self.rate)
        elif self.unit_cost is not None and self.currency_rate is not None:
            rate = money(exact(self.unit_cost) * exact(self.currency_rate))
        else:
            raise ValueError(
                f"Line {self.item!r} needs either rate, or unit_cost plus currency_rate."
            )
        return rate, money(rate * exact(self.qty))


@dataclass
class Charge:
    """A non-inventory ledger line — freight, handling, insurance, a discount.

    `amount` is always positive; the voucher kind decides which side it lands on.
    """

    ledger: str
    amount: Decimal | int | str
    tally_ledger: str | None = None


@dataclass
class Entry:
    """One side of a journal voucher."""

    ledger: str
    amount: Decimal | int | str
    side: str  # "debit" or "credit"
    tally_ledger: str | None = None

    def __post_init__(self):
        if self.side not in ("debit", "credit"):
            raise ValueError(f"side must be 'debit' or 'credit', got {self.side!r}")


@dataclass
class Voucher:
    """A voucher waiting to be gated, priced and posted.

    Build one with Voucher.purchase(), .sales() or .journal() rather than
    constructing it directly.
    """

    kind: str
    voucher_number: str
    date: str  # YYYYMMDD
    voucher_type: str  # the voucher type name as spelled in Tally

    party: str | None = None
    lines: list[Line] = field(default_factory=list)
    charges: list[Charge] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    item_ledger: str | None = None  # Purchase Accounts / Sales Accounts
    reference: str = ""
    reference_date: str | None = None
    narration: str = ""
    country: str | None = None

    round_off_ledger: str | None = None
    invoice_total: Decimal | int | str | None = None

    # filled in by prepare()
    tally_party: str | None = None
    tally_item_ledger: str | None = None
    goods: Decimal = Decimal("0.00")
    charges_total: Decimal = Decimal("0.00")
    round_off: Decimal = Decimal("0.00")
    party_total: Decimal = Decimal("0.00")
    prepared: bool = False

    @classmethod
    def purchase(
        cls,
        voucher_number: str,
        date: str,
        party: str,
        lines: list[Line],
        item_ledger: str,
        voucher_type: str = "Purchase",
        charges: list[Charge] | None = None,
        reference: str = "",
        reference_date: str | None = None,
        narration: str = "",
        country: str | None = None,
        round_off_ledger: str | None = None,
        invoice_total=None,
    ) -> "Voucher":
        """A purchase (supplier bill). Debits stock and the purchase ledger,
        credits the supplier.

        `item_ledger` is YOUR chart of accounts — whatever the purchase ledger is
        called in your Tally, e.g. "Purchase Accounts". There is deliberately no
        default: a wrong-but-plausible default would be posted without anyone
        noticing.

        `invoice_total` plus `round_off_ledger` pins the party total to the
        supplier's own invoice and books the residue as rounding.
        """
        return cls(
            kind="purchase",
            voucher_number=voucher_number,
            date=date,
            voucher_type=voucher_type,
            party=party,
            lines=list(lines),
            charges=list(charges or []),
            item_ledger=item_ledger,
            reference=reference,
            reference_date=reference_date,
            narration=narration,
            country=country,
            round_off_ledger=round_off_ledger,
            invoice_total=invoice_total,
        )

    @classmethod
    def sales(
        cls,
        voucher_number: str,
        date: str,
        party: str,
        lines: list[Line],
        item_ledger: str,
        voucher_type: str = "Sales",
        charges: list[Charge] | None = None,
        reference: str = "",
        reference_date: str | None = None,
        narration: str = "",
        round_off_ledger: str | None = None,
        invoice_total=None,
    ) -> "Voucher":
        """A sale (customer invoice). Credits stock and the sales ledger,
        debits the customer.

        NOT verified against a real Tally sales voucher — see MATURITY above.
        """
        warnings.warn(UNVERIFIED.format(kind="sales"), UserWarning, stacklevel=2)
        return cls(
            kind="sales",
            voucher_number=voucher_number,
            date=date,
            voucher_type=voucher_type,
            party=party,
            lines=list(lines),
            charges=list(charges or []),
            item_ledger=item_ledger,
            reference=reference,
            reference_date=reference_date,
            narration=narration,
            round_off_ledger=round_off_ledger,
            invoice_total=invoice_total,
        )

    @classmethod
    def journal(
        cls,
        voucher_number: str,
        date: str,
        entries: list[Entry],
        voucher_type: str = "Journal",
        narration: str = "",
        reference: str = "",
    ) -> "Voucher":
        """A journal voucher — ledger entries only, no inventory.

        Debits must equal credits; prepare() refuses an unbalanced voucher.

        NOT verified against a real Tally journal voucher — see MATURITY above.
        """
        warnings.warn(UNVERIFIED.format(kind="journal"), UserWarning, stacklevel=2)
        return cls(
            kind="journal",
            voucher_number=voucher_number,
            date=date,
            voucher_type=voucher_type,
            entries=list(entries),
            narration=narration,
            reference=reference,
        )

    # ------------------------------------------------------------------ XML

    def body(self) -> str:
        """The <TALLYMESSAGE> for this voucher. Contains no credentials, so it
        is safe to print, log, diff or hand to an agent for review."""
        if not self.prepared:
            from .errors import NotPrepared

            raise NotPrepared(
                "Voucher has not passed the gate. Call tally.prepare(voucher) "
                "first — it resolves every name against Tally and computes the "
                "money. Nothing should ever be built from unresolved names."
            )
        parts = [
            f'<VOUCHER VCHTYPE="{esc(self.voucher_type)}" ACTION="Create"'
            f'{" OBJVIEW=\"Invoice Voucher View\"" if self.lines else ""}>',
            f"<DATE>{self.date}</DATE>",
            f"<EFFECTIVEDATE>{self.date}</EFFECTIVEDATE>",
            f"<VOUCHERTYPENAME>{esc(self.voucher_type)}</VOUCHERTYPENAME>",
            f"<VOUCHERNUMBER>{esc(self.voucher_number)}</VOUCHERNUMBER>",
            f"<NARRATION>{esc(self.narration)}</NARRATION>",
            "<ISDELETED>No</ISDELETED><ISCANCELLED>No</ISCANCELLED>",
        ]
        if self.reference:
            parts.append(f"<REFERENCE>{esc(self.reference)}</REFERENCE>")
        if self.reference_date:
            parts.append(f"<REFERENCEDATE>{self.reference_date}</REFERENCEDATE>")
        if self.country:
            parts.append(f"<COUNTRYOFRESIDENCE>{esc(self.country)}</COUNTRYOFRESIDENCE>")

        if self.kind == "journal":
            parts.extend(self._journal_entries())
        else:
            parts.extend(self._invoice_body())

        parts.append("</VOUCHER>")
        return '<TALLYMESSAGE xmlns:UDF="TallyUDF">' + "".join(parts) + "</TALLYMESSAGE>"

    def _invoice_body(self) -> list[str]:
        buying = self.kind == "purchase"
        # Goods: debit on a purchase (negative), credit on a sale (positive).
        goods_sign = "-" if buying else ""
        deemed_positive = "Yes" if buying else "No"
        parts = [
            f"<PARTYNAME>{esc(self.tally_party)}</PARTYNAME>",
            f"<PARTYLEDGERNAME>{esc(self.tally_party)}</PARTYLEDGERNAME>",
            f"<BASICBASEPARTYNAME>{esc(self.tally_party)}</BASICBASEPARTYNAME>",
            "<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>",
            "<VCHENTRYMODE>Item Invoice</VCHENTRYMODE>",
            "<ISINVOICE>Yes</ISINVOICE>",
        ]
        for line in self.lines:
            unit = line.resolved_unit or "Nos"
            parts.append(
                "<ALLINVENTORYENTRIES.LIST>"
                f"<STOCKITEMNAME>{esc(line.tally_item)}</STOCKITEMNAME>"
                f"<ISDEEMEDPOSITIVE>{deemed_positive}</ISDEEMEDPOSITIVE>"
                f"<ISLASTDEEMEDPOSITIVE>{deemed_positive}</ISLASTDEEMEDPOSITIVE>"
                "<ISAUTONEGATE>No</ISAUTONEGATE>"
                f"<RATE>{line.resolved_rate}/{esc(unit)}</RATE>"
                f"<AMOUNT>{goods_sign}{line.amount}</AMOUNT>"
                f"<ACTUALQTY> {line.qty} {esc(unit)}</ACTUALQTY>"
                f"<BILLEDQTY> {line.qty} {esc(unit)}</BILLEDQTY>"
                "<ACCOUNTINGALLOCATIONS.LIST>"
                f"<LEDGERNAME>{esc(self.tally_item_ledger)}</LEDGERNAME>"
                f"<ISDEEMEDPOSITIVE>{deemed_positive}</ISDEEMEDPOSITIVE>"
                f"<AMOUNT>{goods_sign}{line.amount}</AMOUNT>"
                "</ACCOUNTINGALLOCATIONS.LIST>"
                "</ALLINVENTORYENTRIES.LIST>"
            )

        # Party: credited on a purchase (positive), debited on a sale (negative).
        party_sign = "" if buying else "-"
        parts.append(
            "<LEDGERENTRIES.LIST>"
            f"<LEDGERNAME>{esc(self.tally_party)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'No' if buying else 'Yes'}</ISDEEMEDPOSITIVE>"
            "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>"
            f"<AMOUNT>{party_sign}{self.party_total}</AMOUNT>"
            "</LEDGERENTRIES.LIST>"
        )
        for charge in self.charges:
            amount = money(charge.amount)
            if not amount:
                continue
            parts.append(
                "<LEDGERENTRIES.LIST>"
                f"<LEDGERNAME>{esc(charge.tally_ledger)}</LEDGERNAME>"
                f"<ISDEEMEDPOSITIVE>{deemed_positive}</ISDEEMEDPOSITIVE>"
                "<ISPARTYLEDGER>No</ISPARTYLEDGER>"
                f"<AMOUNT>{goods_sign}{amount}</AMOUNT>"
                "</LEDGERENTRIES.LIST>"
            )
        if self.round_off and self.round_off_ledger:
            parts.append(
                "<LEDGERENTRIES.LIST>"
                f"<LEDGERNAME>{esc(self.round_off_ledger)}</LEDGERNAME>"
                f"<ISDEEMEDPOSITIVE>{'Yes' if self.round_off < 0 else 'No'}</ISDEEMEDPOSITIVE>"
                "<ISPARTYLEDGER>No</ISPARTYLEDGER>"
                f"<AMOUNT>{-self.round_off}</AMOUNT>"
                "</LEDGERENTRIES.LIST>"
            )
        return parts

    def _journal_entries(self) -> list[str]:
        parts = []
        for entry in self.entries:
            amount = money(entry.amount)
            signed = -amount if entry.side == "debit" else amount
            parts.append(
                "<LEDGERENTRIES.LIST>"
                f"<LEDGERNAME>{esc(entry.tally_ledger)}</LEDGERNAME>"
                f"<ISDEEMEDPOSITIVE>{'Yes' if entry.side == 'debit' else 'No'}</ISDEEMEDPOSITIVE>"
                "<ISPARTYLEDGER>No</ISPARTYLEDGER>"
                f"<AMOUNT>{signed}</AMOUNT>"
                "</LEDGERENTRIES.LIST>"
            )
        return parts

"""Money, XML shape, and the read-back check."""
import warnings
from decimal import Decimal

import pytest

from tally_aiagent import Charge, Entry, Line, VerificationError, Voucher


def purchase(**overrides):
    kwargs = dict(
        voucher_number="PUR-001",
        date="20260909",
        party="Acme Supplies Pvt Ltd",
        item_ledger="Purchase Accounts",
        lines=[Line(item="Widget A", qty=10, rate="125.50")],
    )
    kwargs.update(overrides)
    return Voucher.purchase(**kwargs)


def register(number="PUR-001", goods="1255.00", party="1255.00", lines=1,
             party_name="Acme Supplies Pvt Ltd"):
    entries = "".join(
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Widget A</STOCKITEMNAME>"
        f"<AMOUNT>-{Decimal(goods) / lines}</AMOUNT><ACTUALQTY> 10 Nos</ACTUALQTY>"
        "<RATE>125.50/Nos</RATE></ALLINVENTORYENTRIES.LIST>"
        for _ in range(lines)
    )
    return (
        "<ENVELOPE><VOUCHER>"
        f"<VOUCHERNUMBER>{number}</VOUCHERNUMBER><GUID>v-abc</GUID>"
        f"<DATE>20260909</DATE><PARTYLEDGERNAME>{party_name}</PARTYLEDGERNAME>"
        f"{entries}"
        f"<LEDGERENTRIES.LIST><LEDGERNAME>{party_name}</LEDGERNAME>"
        f"<ISPARTYLEDGER>Yes</ISPARTYLEDGER><AMOUNT>{party}</AMOUNT></LEDGERENTRIES.LIST>"
        "</VOUCHER></ENVELOPE>"
    )


# ------------------------------------------------------------------- money

def test_rate_is_rounded_before_multiplying(tally):
    """1.005 * 3 is 3.02 if you round the rate first, 3.015->3.02 either way;
    0.335 * 3 separates them: rate-first gives 1.02, total-first gives 1.01."""
    voucher = purchase(lines=[Line(item="Widget A", qty=3, unit_cost="0.067", currency_rate="5")])
    tally.prepare(voucher)
    assert voucher.lines[0].resolved_rate == Decimal("0.34")   # 0.335 -> 0.34
    assert voucher.lines[0].amount == Decimal("1.02")          # 0.34 * 3


def test_foreign_currency_purchase(tally):
    voucher = purchase(lines=[Line(item="Widget A", qty=4, unit_cost="10.25", currency_rate="88.40")])
    tally.prepare(voucher)
    assert voucher.lines[0].resolved_rate == Decimal("906.10")
    assert voucher.goods == Decimal("3624.40")


def test_charges_add_to_the_party_total(tally):
    voucher = purchase(charges=[Charge(ledger="Freight Inward", amount="245.50")])
    tally.prepare(voucher)
    assert voucher.goods == Decimal("1255.00")
    assert voucher.charges_total == Decimal("245.50")
    assert voucher.party_total == Decimal("1500.50")


def test_invoice_total_pins_the_party_and_books_the_residue(tally):
    voucher = purchase(
        charges=[Charge(ledger="Freight Inward", amount="245.50")],
        round_off_ledger="Round Off",
        invoice_total="1500.00",
    )
    tally.prepare(voucher)
    assert voucher.round_off == Decimal("-0.50")
    assert voucher.party_total == Decimal("1500.00")


def test_no_floats_anywhere(tally):
    voucher = purchase(lines=[Line(item="Widget A", qty=3, rate=0.1)])
    tally.prepare(voucher)
    assert isinstance(voucher.goods, Decimal)
    assert voucher.goods == Decimal("0.30")


# --------------------------------------------------------------- XML shape

def test_purchase_debits_goods_and_credits_the_party(tally):
    preparation = tally.prepare(purchase())
    assert "<AMOUNT>-1255.00</AMOUNT>" in preparation.xml       # goods, debit
    assert "<AMOUNT>1255.00</AMOUNT>" in preparation.xml        # party, credit
    assert "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" in preparation.xml


def test_sales_mirrors_the_signs(tally):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        voucher = Voucher.sales(
            voucher_number="SAL-001",
            date="20260909",
            party="Beta Traders & Co",
            item_ledger="Sales Accounts",
            lines=[Line(item="Widget A", qty=2, rate="500")],
        )
    preparation = tally.prepare(voucher)
    assert "<AMOUNT>1000.00</AMOUNT>" in preparation.xml        # goods, credit
    assert "<AMOUNT>-1000.00</AMOUNT>" in preparation.xml       # party, debit


def test_the_tally_spelling_is_written_not_ours(tally):
    preparation = tally.prepare(purchase(party="acme supplies pvt ltd"))
    assert "<PARTYNAME>Acme Supplies Pvt Ltd</PARTYNAME>" in preparation.xml
    assert "acme supplies pvt ltd" not in preparation.xml


def test_units_come_from_the_master_not_a_guess(tally):
    preparation = tally.prepare(purchase(lines=[Line(item="Cable, 2m", qty=5, rate="20")]))
    assert "<ACTUALQTY> 5 Pcs</ACTUALQTY>" in preparation.xml
    assert "Nos" not in preparation.xml


def test_ampersand_in_a_name_is_escaped(tally):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        voucher = Voucher.sales(
            voucher_number="SAL-002", date="20260909", party="Beta Traders & Co",
            item_ledger="Sales Accounts", lines=[Line(item="Widget A", qty=1, rate="1")],
        )
    preparation = tally.prepare(voucher)
    assert "Beta Traders &amp; Co" in preparation.xml
    assert "Beta Traders & Co" not in preparation.xml


def test_prepared_xml_carries_no_credentials(tally):
    """The body is safe to show a human or hand to an agent."""
    tally.config.user, tally.config.password = "admin", "hunter2"
    preparation = tally.prepare(purchase())
    assert "hunter2" not in preparation.xml
    assert "PASSWORD" not in preparation.xml


def test_journal_entries_carry_the_right_signs(tally):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        voucher = Voucher.journal(
            voucher_number="JV-001", date="20260909",
            entries=[
                Entry(ledger="Freight Inward", amount="500", side="debit"),
                Entry(ledger="Bank Account", amount="500", side="credit"),
            ],
        )
    preparation = tally.prepare(voucher)
    assert "<AMOUNT>-500.00</AMOUNT>" in preparation.xml
    assert "<AMOUNT>500.00</AMOUNT>" in preparation.xml
    assert "ALLINVENTORYENTRIES" not in preparation.xml


# ------------------------------------------------------ read-back check

def test_a_clean_post_reports_no_differences(tally):
    tally.voucher_register_xml = register()
    result = tally.post(tally.prepare(purchase()))
    assert result["posted"] is True
    assert result["differences"] == []
    assert result["guid"] == "v-abc"


def test_created_is_not_proof_a_wrong_total_is_caught(tally):
    """Tally says CREATED=1 and stored a different number."""
    tally.voucher_register_xml = register(goods="1255.00", party="9999.00")
    result = tally.post(tally.prepare(purchase()))
    assert result["posted"] is True
    assert any("party total" in d for d in result["differences"])


def test_a_missing_voucher_is_caught(tally):
    tally.voucher_register_xml = "<ENVELOPE></ENVELOPE>"
    result = tally.post(tally.prepare(purchase()))
    assert result["differences"] == ["Voucher was not found in Tally when reading it back."]


def test_strict_mode_raises_on_a_mismatch(tally):
    tally.voucher_register_xml = register(party="9999.00")
    with pytest.raises(VerificationError) as excinfo:
        tally.post(tally.prepare(purchase()), verify="strict")
    assert excinfo.value.voucher_number == "PUR-001"
    assert "Nothing has been rolled back" in str(excinfo.value)


def test_a_silently_created_duplicate_party_is_caught(tally):
    """The exact failure this library exists for, seen from the other end."""
    tally.voucher_register_xml = register(party_name="Acme Supplies Co Ltd")
    result = tally.post(tally.prepare(purchase()))
    assert any("party:" in d for d in result["differences"])


def test_import_errors_are_surfaced_not_swallowed(tally):
    tally.import_response = (
        "<ENVELOPE><CREATED>0</CREATED><ERRORS>1</ERRORS>"
        "<LINEERROR>Ledger 'Whatever' does not exist</LINEERROR></ENVELOPE>"
    )
    result = tally.post(tally.prepare(purchase()))
    assert result["posted"] is False
    assert "Whatever" in result["lineerrors"][0]


def test_verify_off_does_not_read_back(tally):
    result = tally.post(tally.prepare(purchase()), verify="off")
    assert result["differences"] == []
    assert not any("Voucher Register" in sent for sent in tally.sent)


# ----------------------------------------------------------------- other

def test_stock_summary_reads_quantities(tally):
    assert tally.stock_summary() == {"Widget A": 14.0, "Widget B": 3.0}


def test_next_voucher_number_reads_the_live_maximum(tally):
    tally.voucher_register_xml = (
        "<ENVELOPE><VOUCHERNUMBER>PUR-001/2627</VOUCHERNUMBER>"
        "<VOUCHERNUMBER>PUR-003/2627</VOUCHERNUMBER></ENVELOPE>"
    )
    suggested, warning = tally.next_voucher_number("PUR", "Purchase", "20260909")
    assert suggested == "PUR-004/2627"
    assert "002" in warning        # the gap is reported, not silently skipped


def test_financial_year_straddles_april(tally):
    tally.voucher_register_xml = "<ENVELOPE></ENVELOPE>"
    suggested, _ = tally.next_voucher_number("PUR", "Purchase", "20260215")
    assert suggested == "PUR-001/2526"      # Feb 2026 is FY 2025-26


def test_journal_uses_the_three_L_tag(tally):
    """ALLLEDGERENTRIES.LIST, not LEDGERENTRIES.LIST. Tally rejects the wrong one
    with EXCEPTIONS=1 and no message at all — verified against a live company."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        voucher = Voucher.journal(
            voucher_number="JV-002", date="20260909",
            entries=[Entry(ledger="Freight Inward", amount="500", side="debit"),
                     Entry(ledger="Bank Account", amount="500", side="credit")],
        )
    xml = tally.prepare(voucher).xml
    assert "<ALLLEDGERENTRIES.LIST>" in xml
    assert "<LEDGERENTRIES.LIST>" not in xml.replace("<ALLLEDGERENTRIES.LIST>", "")


def test_autonumbered_type_is_read_back_by_master_id(tally):
    """Tally ignores the number you send on an auto-numbered type and assigns
    its own. Reading back by the sent number finds nothing; the fallback finds
    it by the id Tally reports, so a good post is not reported as a failure."""
    tally.import_response = (
        "<ENVELOPE><CREATED>1</CREATED><ERRORS>0</ERRORS><EXCEPTIONS>0</EXCEPTIONS>"
        "<LASTMID>634</LASTMID></ENVELOPE>"
    )
    tally.voucher_register_xml = (
        "<ENVELOPE><VOUCHER><VOUCHERNUMBER>14</VOUCHERNUMBER><MASTERID>634</MASTERID>"
        "<GUID>v-auto</GUID><DATE>20260909</DATE>"
        "<PARTYLEDGERNAME>Acme Supplies Pvt Ltd</PARTYLEDGERNAME>"
        "<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>Widget A</STOCKITEMNAME>"
        "<AMOUNT>-1255.00</AMOUNT><ACTUALQTY> 10 Nos</ACTUALQTY><RATE>125.50/Nos</RATE>"
        "</ALLINVENTORYENTRIES.LIST>"
        "<LEDGERENTRIES.LIST><LEDGERNAME>Acme Supplies Pvt Ltd</LEDGERNAME>"
        "<ISPARTYLEDGER>Yes</ISPARTYLEDGER><AMOUNT>1255.00</AMOUNT></LEDGERENTRIES.LIST>"
        "</VOUCHER></ENVELOPE>"
    )
    result = tally.post(tally.prepare(purchase(voucher_number="WHATEVER-WE-SENT")))
    assert result["posted"] is True
    assert result["differences"] == []
    assert result["assigned_voucher_number"] == "14"

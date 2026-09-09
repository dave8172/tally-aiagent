"""The gate. Every test here is a write that must NOT happen."""
import warnings

import pytest

from tally_aiagent import Charge, Entry, GateError, Line, NotPrepared, Voucher


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


def test_masters_are_read_from_tally(tally):
    masters = tally.masters()
    assert len(masters.items) == 5           # the deleted item is skipped
    assert "Retired Item" not in masters.items
    assert len(masters.ledgers) == 7
    assert masters.items["Widget A"]["guid"] == "g-001"


def test_hsn_is_inherited_from_the_stock_group(tally):
    masters = tally.masters()
    assert masters.items["Widget A"]["hsn"] == "90304000"   # from the group
    assert masters.items["Widget B"]["hsn"] == "85176290"   # own value wins


def test_xml_entities_in_master_names_survive(tally):
    masters = tally.masters()
    assert "Beta Traders & Co" in masters.ledgers


def test_exact_name_resolves(tally):
    name, how = tally.masters().resolve_ledger("Acme Supplies Pvt Ltd")
    assert name == "Acme Supplies Pvt Ltd"
    assert how == "exact"


def test_punctuation_difference_resolves_to_the_tally_spelling(tally):
    """The whole failure mode: our name differs, Tally's spelling gets written."""
    name, how = tally.masters().resolve_ledger("ACME SUPPLIES PVT. LTD.")
    assert name == "Acme Supplies Pvt Ltd"
    assert "normalized" in how


def test_unknown_supplier_is_refused_and_nothing_is_sent(tally):
    voucher = purchase(party="Acme Supplies Co. Ltd")
    with pytest.raises(GateError) as excinfo:
        tally.prepare(voucher)
    assert "Acme Supplies Co. Ltd" in str(excinfo.value)
    assert not any("Import" in sent for sent in tally.sent)


def test_unknown_item_is_refused(tally):
    voucher = purchase(lines=[Line(item="Widget Q", qty=1, rate="10")])
    with pytest.raises(GateError, match="Widget Q"):
        tally.prepare(voucher)


def test_ambiguity_is_refused_never_guessed(tally):
    """'PSU 500H' and 'PSU 500-H' normalize alike. There is no safe answer."""
    voucher = purchase(lines=[Line(item="PSU500H", qty=1, rate="10")])
    with pytest.raises(GateError) as excinfo:
        tally.prepare(voucher)
    assert "ambiguous" in str(excinfo.value)


def test_every_problem_is_reported_at_once(tally):
    voucher = purchase(
        party="Nobody Ltd",
        item_ledger="No Such Ledger",
        lines=[Line(item="Widget A", qty=1, rate="10"), Line(item="Widget Z", qty=1, rate="10")],
    )
    with pytest.raises(GateError) as excinfo:
        tally.prepare(voucher)
    message = str(excinfo.value)
    assert "Nobody Ltd" in message and "No Such Ledger" in message and "Widget Z" in message


def test_refusal_suggests_lookalikes_without_choosing(tally):
    voucher = purchase(party="Acme")
    with pytest.raises(GateError) as excinfo:
        tally.prepare(voucher)
    assert "did you mean" in str(excinfo.value)
    assert "Acme Supplies Pvt Ltd" in str(excinfo.value)


def test_unknown_charge_ledger_is_refused(tally):
    voucher = purchase(charges=[Charge(ledger="Freight Inwards", amount="500")])
    with pytest.raises(GateError, match="Freight Inwards"):
        tally.prepare(voucher)


def test_empty_voucher_is_refused(tally):
    with pytest.raises(GateError, match="no inventory lines"):
        tally.prepare(purchase(lines=[]))


def test_invoice_total_without_roundoff_ledger_is_refused(tally):
    with pytest.raises(GateError, match="nowhere to book"):
        tally.prepare(purchase(invoice_total="2000"))


def test_body_cannot_be_built_before_the_gate_runs():
    with pytest.raises(NotPrepared):
        purchase().body()


def test_post_refuses_a_raw_voucher(tally):
    with pytest.raises(NotPrepared):
        tally.post(purchase())


def test_journal_must_balance(tally):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        voucher = Voucher.journal(
            voucher_number="JV-001",
            date="20260909",
            entries=[
                Entry(ledger="Freight Inward", amount="500", side="debit"),
                Entry(ledger="Bank Account", amount="400", side="credit"),
            ],
        )
    with pytest.raises(GateError, match="does not balance"):
        tally.prepare(voucher)


def test_did_you_mean_catches_a_near_miss_where_one_word_differs(tally):
    """The regression this exists for: 'Co. Ltd' vs 'Pvt Ltd' share no substring,
    and it is the single most likely way to accidentally create a duplicate."""
    suggestions = tally.masters().candidates("Acme Supplies Co. Ltd", kind="ledger")
    assert "Acme Supplies Pvt Ltd" in suggestions


def test_did_you_mean_still_catches_a_partial(tally):
    assert "Acme Supplies Pvt Ltd" in tally.masters().candidates("Acme", kind="ledger")


def test_did_you_mean_does_not_return_everything(tally):
    assert tally.masters().candidates("zzzzzzzz", kind="ledger") == []


def test_masters_populated_after_construction_still_resolve():
    """A caller may build Masters and fill it in afterwards — a test fixture, or
    a master list cached elsewhere. An index built once at construction would
    match nothing, which is the one failure this class must never have."""
    from tally_aiagent import Masters

    masters = Masters()
    masters.ledgers["Acme Supplies Pvt Ltd"] = {"guid": "l-1", "parent": "Sundry Creditors"}
    masters.items["Widget A"] = {"guid": "g-1", "parent": "Grp", "hsn": None, "units": "Nos"}

    assert masters.resolve_ledger("ACME SUPPLIES PVT. LTD.")[0] == "Acme Supplies Pvt Ltd"
    assert masters.resolve_item("widget a")[0] == "Widget A"

    masters.ledgers["Beta Traders"] = {"guid": "l-2", "parent": "Sundry Debtors"}
    assert masters.resolve_ledger("beta traders")[0] == "Beta Traders"

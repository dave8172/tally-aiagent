"""The CLI, driven end to end against the fake Tally."""
import json

import pytest
from click.testing import CliRunner

from tally_aiagent import cli

from conftest import FakeTally


@pytest.fixture
def run(monkeypatch):
    fake = FakeTally()
    monkeypatch.setattr(cli, "_client", lambda: fake)
    runner = CliRunner()

    def invoke(args, **kwargs):
        return runner.invoke(cli.main, args, **kwargs)

    invoke.fake = fake
    return invoke


def test_check_reports_what_tally_holds(run):
    result = run(["check"])
    assert result.exit_code == 0
    assert "5 stock items" in result.output
    assert "7 ledgers" in result.output
    assert "connection ok" in result.output


def test_resolve_shows_the_tally_spelling(run):
    result = run(["resolve", "acme supplies pvt. ltd."])
    assert result.exit_code == 0
    assert "Acme Supplies Pvt Ltd" in result.output


def test_resolve_refuses_and_exits_nonzero(run):
    result = run(["resolve", "Acme Supplies Co. Ltd"])
    assert result.exit_code == 1
    assert "REFUSED" in result.output
    assert "did you mean" in result.output
    assert "would create a new master" in result.output


def test_masters_lists_names(run):
    result = run(["masters", "--kind", "items", "--search", "widget"])
    assert result.exit_code == 0
    assert "Widget A" in result.output and "Cable, 2m" not in result.output


def test_stock_prints_quantities(run):
    result = run(["stock"])
    assert "Widget A" in result.output and "14" in result.output


def test_prepare_is_a_dry_run_by_default(run, tmp_path):
    spec = tmp_path / "v.json"
    spec.write_text(json.dumps({
        "kind": "purchase",
        "voucher_number": "PUR-001",
        "date": "20260909",
        "party": "Acme Supplies Pvt Ltd",
        "item_ledger": "Purchase Accounts",
        "lines": [{"item": "Widget A", "qty": 2, "rate": "100"}],
    }))
    result = run(["prepare", str(spec)])
    assert result.exit_code == 0
    assert "dry run — nothing was written" in result.output
    assert not any("Import" in sent for sent in run.fake.sent)


def test_prepare_refuses_an_unknown_name_and_writes_nothing(run, tmp_path):
    spec = tmp_path / "v.json"
    spec.write_text(json.dumps({
        "kind": "purchase",
        "voucher_number": "PUR-001",
        "date": "20260909",
        "party": "Ghost Supplier Ltd",
        "item_ledger": "Purchase Accounts",
        "lines": [{"item": "Widget A", "qty": 2, "rate": "100"}],
    }))
    result = run(["prepare", str(spec), "--post"])
    assert result.exit_code == 1
    assert "Refusing to post" in result.output
    assert "Nothing was sent to Tally" in result.output
    assert not any("Import" in sent for sent in run.fake.sent)


def test_examples_in_the_repo_are_loadable(run):
    """The shipped examples must actually parse — a broken sample is a dead end
    on first contact."""
    import glob
    for path in sorted(glob.glob("examples/*.json")):
        data = json.load(open(path))
        assert "kind" in data and "voucher_number" in data

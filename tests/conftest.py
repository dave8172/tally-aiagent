"""A fake Tally that answers from canned XML — no network, no Tally install."""
import pytest

from tally_aiagent import Tally

STOCK_ITEMS_XML = """<ENVELOPE>
<STOCKGROUP NAME="Test Instruments"><HSNCODE>90304000</HSNCODE></STOCKGROUP>
<STOCKITEM NAME="Widget A"><GUID>g-001</GUID><PARENT>Test Instruments</PARENT>
  <BASEUNITS>Nos</BASEUNITS></STOCKITEM>
<STOCKITEM NAME="Widget B"><GUID>g-002</GUID><PARENT>Test Instruments</PARENT>
  <BASEUNITS>Nos</BASEUNITS><HSNCODE>85176290</HSNCODE></STOCKITEM>
<STOCKITEM NAME="Cable, 2m"><GUID>g-003</GUID><PARENT>Test Instruments</PARENT>
  <BASEUNITS>Pcs</BASEUNITS></STOCKITEM>
<STOCKITEM NAME="PSU 500H"><GUID>g-004</GUID><PARENT>Test Instruments</PARENT>
  <BASEUNITS>Nos</BASEUNITS></STOCKITEM>
<STOCKITEM NAME="PSU 500-H"><GUID>g-005</GUID><PARENT>Test Instruments</PARENT>
  <BASEUNITS>Nos</BASEUNITS></STOCKITEM>
<STOCKITEM NAME="Retired Item"><GUID>g-006</GUID><ISDELETED>Yes</ISDELETED></STOCKITEM>
</ENVELOPE>"""

LEDGERS_XML = """<ENVELOPE>
<LEDGER NAME="Acme Supplies Pvt Ltd"><GUID>l-001</GUID><PARENT>Sundry Creditors</PARENT></LEDGER>
<LEDGER NAME="Beta Traders &amp; Co"><GUID>l-002</GUID><PARENT>Sundry Debtors</PARENT></LEDGER>
<LEDGER NAME="Purchase Accounts"><GUID>l-003</GUID><PARENT>Purchase Accounts</PARENT></LEDGER>
<LEDGER NAME="Sales Accounts"><GUID>l-004</GUID><PARENT>Sales Accounts</PARENT></LEDGER>
<LEDGER NAME="Freight Inward"><GUID>l-005</GUID><PARENT>Direct Expenses</PARENT></LEDGER>
<LEDGER NAME="Round Off"><GUID>l-006</GUID><PARENT>Indirect Expenses</PARENT></LEDGER>
<LEDGER NAME="Bank Account"><GUID>l-007</GUID><PARENT>Bank Accounts</PARENT></LEDGER>
</ENVELOPE>"""

STOCK_SUMMARY_XML = """<ENVELOPE>
<DSPDISPNAME>Widget A</DSPDISPNAME><DSPCLQTY> 14 Nos</DSPCLQTY>
<DSPDISPNAME>Widget B</DSPDISPNAME><DSPCLQTY> 3 Nos</DSPCLQTY>
</ENVELOPE>"""


class FakeTally(Tally):
    """Records what would have been sent; replays canned responses."""

    def __init__(self, **kwargs):
        super().__init__(host="fake", company="Test Co", **kwargs)
        self.sent: list[str] = []
        self.import_response = (
            "<ENVELOPE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS>"
            "<EXCEPTIONS>0</EXCEPTIONS><LASTVCHID>42</LASTVCHID></ENVELOPE>"
        )
        self.voucher_register_xml = "<ENVELOPE></ENVELOPE>"

    def _send(self, xml, timeout):
        self.sent.append(xml)
        if "<TALLYREQUEST>Import</TALLYREQUEST>" in xml:
            return self.import_response
        if "Stock Items" in xml:
            return STOCK_ITEMS_XML
        if "Ledgers" in xml:
            return LEDGERS_XML
        if "Stock Summary" in xml:
            return STOCK_SUMMARY_XML
        if "Voucher Register" in xml:
            return self.voucher_register_xml
        return "<ENVELOPE></ENVELOPE>"


@pytest.fixture
def tally():
    return FakeTally()

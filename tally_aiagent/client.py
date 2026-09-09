"""Connection and transport.

Tally Prime exposes an HTTP XML interface on the machine it runs on — by
default port 9000, often 9008 on hosted/cloud Tally. There is no TLS on that
port: Tally does not support it. Credentials travel in the request body in
clear text, so this connection belongs on a LAN, a VPN or an SSH tunnel and
never on the public internet. See the Security section of the README.
"""
import os
from dataclasses import dataclass
from urllib import request as urllib_request
from urllib.error import URLError

from .errors import NotConfigured, Unreachable
from .xml_util import esc

DEFAULT_PORT = 9000

# Reads are cheap to retry and a stale read is harmless; a write that times out
# may or may not have landed, so writes get one attempt and a long ceiling.
READ_TIMEOUT = 60
WRITE_TIMEOUT = 180


@dataclass
class TallyConfig:
    """Where Tally is and how to authenticate."""

    host: str
    company: str
    port: int = DEFAULT_PORT
    user: str = ""
    password: str = ""

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class Tally:
    """A connection to one Tally company.

    >>> tally = Tally.from_env()
    >>> masters = tally.masters()
    >>> masters.resolve_ledger("acme supplies")
    ('Acme Supplies Pvt Ltd', 'normalized')
    """

    def __init__(
        self,
        host: str,
        company: str,
        port: int = DEFAULT_PORT,
        user: str = "",
        password: str = "",
    ):
        if not host:
            raise NotConfigured("No Tally host given.")
        if not company:
            raise NotConfigured(
                "No company name given. Tally needs to know which company to "
                "act on, exactly as it is spelled in Tally's company list."
            )
        self.config = TallyConfig(
            host=host, company=company, port=port, user=user, password=password
        )
        self._masters = None

    @classmethod
    def from_env(cls) -> "Tally":
        """Build from TALLY_HOST / TALLY_PORT / TALLY_COMPANY / TALLY_USER /
        TALLY_PASSWORD environment variables."""
        host = os.environ.get("TALLY_HOST", "").strip()
        company = os.environ.get("TALLY_COMPANY", "").strip()
        if not host or not company:
            raise NotConfigured(
                "Set TALLY_HOST and TALLY_COMPANY (and TALLY_PORT / TALLY_USER "
                "/ TALLY_PASSWORD if your Tally needs them). TALLY_COMPANY must "
                "match the company name in Tally exactly."
            )
        return cls(
            host=host,
            company=company,
            port=int(os.environ.get("TALLY_PORT", DEFAULT_PORT)),
            user=os.environ.get("TALLY_USER", ""),
            password=os.environ.get("TALLY_PASSWORD", ""),
        )

    # -------------------------------------------------------------- transport

    def _header(self, request: str, report_id: str) -> str:
        """The authenticated envelope header. The ONLY place credentials appear."""
        return (
            "<HEADER><VERSION>1</VERSION>"
            f"<TALLYREQUEST>{request}</TALLYREQUEST><TYPE>Data</TYPE>"
            f"<ID>{esc(report_id)}</ID>"
            f"<USERID>{esc(self.config.user)}</USERID>"
            f"<PASSWORD>{esc(self.config.password)}</PASSWORD></HEADER>"
        )

    def _send(self, xml: str, timeout: int) -> str:
        request = urllib_request.Request(
            self.config.url,
            data=xml.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except URLError as exc:
            raise Unreachable(
                f"Could not reach Tally at {self.config.url} ({exc.reason}). "
                "Is Tally running, is the company open, and is the XML port "
                "enabled? In Tally: F1 > Settings > Connectivity > Client/Server "
                "configuration > set 'TallyPrime acts as' to 'Both'."
            ) from exc
        except OSError as exc:
            raise Unreachable(f"Could not reach Tally at {self.config.url}: {exc}") from exc

    def export(self, report_id: str, variables: str = "", timeout: int = READ_TIMEOUT) -> str:
        """Run an Export (read) request and return the raw XML response."""
        xml = (
            "<ENVELOPE>"
            + self._header("Export", report_id)
            + "<BODY><DESC><STATICVARIABLES>"
            "<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
            f"<SVCURRENTCOMPANY>{esc(self.config.company)}</SVCURRENTCOMPANY>"
            f"{variables}"
            "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
        )
        return self._send(xml, timeout)

    def import_data(self, body: str, timeout: int = WRITE_TIMEOUT) -> str:
        """Run an Import (write) request. `body` is one or more <TALLYMESSAGE>
        elements, built without credentials — they are added here."""
        xml = (
            "<ENVELOPE>"
            + self._header("Import", "Vouchers")
            + "<BODY><DESC><STATICVARIABLES>"
            f"<SVCURRENTCOMPANY>{esc(self.config.company)}</SVCURRENTCOMPANY>"
            "</STATICVARIABLES></DESC>"
            f"<DATA>{body}</DATA></BODY></ENVELOPE>"
        )
        return self._send(xml, timeout)

    # ---------------------------------------------------------------- masters

    def masters(self, refresh: bool = False):
        """Fetch (and cache) Tally's stock item and ledger masters.

        Cached for the life of this object because the gate consults it on every
        line. Pass refresh=True after someone has added a master in Tally, and
        note that prepare() always re-reads before a post regardless.
        """
        from .masters import fetch_masters

        if self._masters is None or refresh:
            self._masters = fetch_masters(self)
        return self._masters

    # --------------------------------------------------------------- the gate

    def prepare(self, voucher, masters=None):
        """Resolve every name against Tally and compute the money. Sends nothing.

        Returns a Preparation. Raises GateError if any name is unknown or
        ambiguous — in which case nothing was written and nothing can be.
        """
        from .posting import prepare as _prepare

        return _prepare(self, voucher, masters=masters)

    def post(self, preparation, verify: str = "warn") -> dict:
        """Write a prepared voucher, then read it back and compare."""
        from .posting import post as _post

        return _post(self, preparation, verify=verify)

    def read_voucher(self, voucher_number: str, voucher_type: str, on_date: str):
        """Read one voucher back out of Tally."""
        from .posting import read_voucher as _read

        return _read(self, voucher_number, voucher_type, on_date)

    def next_voucher_number(self, prefix: str, voucher_type: str, on_date: str | None = None):
        """Suggest the next free voucher number for a manually numbered type."""
        from .posting import next_voucher_number as _next

        return _next(self, prefix, voucher_type, on_date)

    # ----------------------------------------------------------------- stock

    def stock_summary(self) -> dict:
        """{item_name: closing_qty}. Items absent from the response are at zero."""
        from .stock import stock_summary as _summary

        return _summary(self)

    def item_balance(self, item_name: str):
        """Closing quantity for one item."""
        from .stock import item_balance as _balance

        return _balance(self, item_name)

    def bills_outstanding(self, ledger_name: str) -> list:
        """Open bills against one party ledger."""
        from .stock import bills_outstanding as _bills

        return _bills(self, ledger_name)

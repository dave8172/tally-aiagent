"""Finding Tally, and finding out what it has open, before anything is configured.

Everything here works without a company name — that is the point. Asking someone to
type their company name "exactly as Tally spells it" is the single most reliable way
to make setup fail: Tally is unforgiving about a comma or a trailing space, and gives
no hint at all when it does not match. Read the name out of Tally instead.
"""
import re
from html import unescape
from urllib import request as urllib_request
from urllib.error import URLError

from .xml_util import esc

DEFAULT_PORT = 9000
CLOUD_PORT = 9008

# The whole company list comes back in well under a kilobyte, so this is cheap
# enough to run during setup without anyone noticing.
_COMPANIES = (
    "<ENVELOPE><HEADER><VERSION>1</VERSION>"
    "<TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE>"
    "<ID>List of Accounts</ID>{auth}</HEADER>"
    "<BODY><DESC><STATICVARIABLES>"
    "<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"
    "<ACCOUNTTYPE>Companies</ACCOUNTTYPE>"
    "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
)


def _post(host: str, port: int, xml: str, timeout: int = 15) -> str:
    request = urllib_request.Request(
        f"http://{host}:{port}",
        data=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        method="POST",
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _auth(user: str, password: str) -> str:
    """Empty <USERID></USERID> tags are not the same as no tags — a company without
    security answers the first form with nothing. Send them only when set."""
    if not (user or password):
        return ""
    return f"<USERID>{esc(user)}</USERID><PASSWORD>{esc(password)}</PASSWORD>"


def companies(host, port=DEFAULT_PORT, user="", password="", timeout=15) -> list[str]:
    """Every company Tally has open, by the exact name Tally spells it with.

    Read from <REMOTECMPNAME>. Note that <NAME> in the same response is a GUID, not
    a name — matching on it gets you a company identifier that Tally will not accept
    as a company name.
    """
    raw = _post(host, port, _COMPANIES.format(auth=_auth(user, password)), timeout)
    seen, out = set(), []
    for name in re.findall(r"<REMOTECMPNAME>([^<]*)</REMOTECMPNAME>", raw):
        name = unescape(name).strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def active_company(host, port=DEFAULT_PORT, user="", password="", timeout=15) -> str | None:
    """The company Tally is currently sitting on — what it acts on if you name none."""
    raw = _post(host, port, _COMPANIES.format(auth=_auth(user, password)), timeout)
    match = re.search(r"<SVCURRENTCOMPANY>([^<]*)</SVCURRENTCOMPANY>", raw)
    return unescape(match.group(1)).strip() if match and match.group(1).strip() else None


def reachable(host, port=DEFAULT_PORT, timeout=10) -> tuple[bool, str]:
    """Is something answering, and does it look like Tally? Returns (ok, message)."""
    try:
        raw = _post(host, port, "<ENVELOPE></ENVELOPE>", timeout)
    except URLError as exc:
        return False, str(getattr(exc, "reason", exc))
    except OSError as exc:
        return False, str(exc)
    if raw.strip():
        return True, "Tally answered"
    return False, "something answered, but it does not look like Tally"

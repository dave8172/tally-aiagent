"""Minimal XML helpers.

Tally's HTTP interface speaks a non-standard XML dialect that real parsers
choke on (unescaped ampersands in master names are routine), which is why this
reads with regular expressions rather than ElementTree. That is a deliberate
choice, not an oversight.
"""
import re
from html import unescape


def esc(value) -> str:
    """Escape a value for inclusion in a Tally XML request."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def tag(block: str, name: str) -> str | None:
    """First <name>…</name> value inside `block`, unescaped and stripped."""
    match = re.search(rf"<{name}>([^<]*)</{name}>", block)
    return unescape(match.group(1)).strip() if match else None


def blocks(raw: str, name: str) -> list[str]:
    """Every <name …>…</name> element in `raw`, outermost first."""
    return re.findall(rf"<{name}\b.*?</{name}>", raw, re.S)


def attr(block: str, element: str, name: str) -> str | None:
    """Value of an attribute on an element's opening tag."""
    match = re.search(rf"<{element}\b[^>]*\b{name}=\"([^\"]*)\"", block)
    return unescape(match.group(1)).strip() if match else None


def redact(xml: str) -> str:
    """Strip credentials so a request can be shown to a human or an agent.

    build_body() never contains credentials — they are added at send time — but
    this exists so a raw response or a hand-built envelope can be logged safely.
    """
    xml = re.sub(r"<PASSWORD>[^<]*</PASSWORD>", "<PASSWORD>***</PASSWORD>", xml)
    return re.sub(r"<USERID>[^<]*</USERID>", "<USERID>***</USERID>", xml)

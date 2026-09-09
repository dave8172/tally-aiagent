"""MCP server — Tally for AI agents, with the gate in the way.

The point of this server is what it *refuses* to do.

An agent talking to Tally through a plain connector can name a supplier that
does not quite exist, and Tally will create it rather than complain. So the
write path here is deliberately two calls, not one:

    prepare_voucher(...)   ->  resolves every name, prices it, returns a report
                               and a preparation id. NOTHING is written.
    post_voucher(id)       ->  writes that exact prepared voucher, then reads it
                               back out of Tally and reports any difference.

An agent cannot skip the review step, because post_voucher has no way to
express a voucher — only to name one that already passed the gate. Whoever is
supervising the agent gets a legible report between the two calls.
"""
import json
import os
import uuid

from .errors import GateError, TallyError
from .vouchers import Charge, Entry, Line, Voucher

try:
    from mcp.server import MCPServer
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP extra is not installed. Run: pip install 'tally-aiagent[mcp]'"
    ) from exc

server = MCPServer(
    name="tally-aiagent",
    instructions=(
        "Read and write a Tally Prime company safely.\n\n"
        "CRITICAL: Tally does not reject a ledger or stock item name it has "
        "never seen — it silently creates one and reports success. Never invent "
        "or guess a master name. Use list_masters or resolve_name to find the "
        "exact spelling Tally holds, and if resolve_name reports 'ambiguous', "
        "ask the human which one rather than picking.\n\n"
        "To write: call prepare_voucher, show the human the report it returns, "
        "then call post_voucher with the preparation_id. Never describe a "
        "voucher as posted until post_voucher returns differences: []."
    ),
)

_prepared: dict[str, object] = {}
_tally = None


def _client():
    global _tally
    if _tally is None:
        from .client import Tally

        _tally = Tally.from_env()
    return _tally


def _writes_allowed() -> bool:
    return os.environ.get("TALLY_AIAGENT_ALLOW_WRITES", "").lower() in ("1", "true", "yes")


def _fail(message: str, **extra) -> str:
    return json.dumps({"ok": False, "error": message, **extra}, indent=2, default=str)


def _ok(**payload) -> str:
    return json.dumps({"ok": True, **payload}, indent=2, default=str)


# ---------------------------------------------------------------------- read


@server.tool(
    description=(
        "List the stock items or ledgers that exist in Tally, with their exact "
        "spelling. Always the first stop before naming anything in a voucher."
    )
)
def list_masters(kind: str = "ledgers", search: str = "", limit: int = 50) -> str:
    """kind: 'ledgers' or 'items'. search: optional substring filter."""
    try:
        masters = _client().masters()
    except TallyError as exc:
        return _fail(str(exc))
    table = masters.items if kind.startswith("item") else masters.ledgers
    names = sorted(table)
    if search:
        needle = search.lower()
        names = [n for n in names if needle in n.lower()]
    return _ok(kind=kind, total=len(table), shown=len(names[:limit]), names=names[:limit])


@server.tool(
    description=(
        "Check whether a name can be safely written to Tally. Returns the exact "
        "Tally spelling, or explains why it cannot be resolved. If the answer is "
        "ambiguous, ask the human — do not pick one."
    )
)
def resolve_name(name: str, kind: str = "ledger") -> str:
    """kind: 'ledger' or 'item'."""
    try:
        masters = _client().masters()
    except TallyError as exc:
        return _fail(str(exc))
    if kind.startswith("item"):
        resolved, how = masters.resolve_item(name)
    else:
        resolved, how = masters.resolve_ledger(name)
    if resolved:
        return _ok(resolved=True, tally_name=resolved, matched=how, write_this=resolved)
    return _ok(
        resolved=False,
        reason=how,
        candidates=masters.candidates(name, kind="item" if kind.startswith("item") else "ledger"),
        advice="Do not write this name. Ask the human, or create the master in Tally first.",
    )


@server.tool(description="Closing stock quantity for every item, or one named item.")
def stock(item: str = "") -> str:
    try:
        summary = _client().stock_summary()
    except TallyError as exc:
        return _fail(str(exc))
    if item:
        return _ok(item=item, qty=summary.get(item), known=item in summary)
    return _ok(items=summary, count=len(summary))


@server.tool(
    description=(
        "Read one voucher back out of Tally by its number. Use this to confirm "
        "what the books actually hold rather than trusting an earlier write."
    )
)
def read_voucher(voucher_number: str, voucher_type: str = "Purchase", on_date: str = "") -> str:
    """on_date: any YYYYMMDD date inside the financial year holding the voucher."""
    from datetime import date

    on_date = on_date or date.today().strftime("%Y%m%d")
    try:
        found = _client().read_voucher(voucher_number, voucher_type, on_date)
    except TallyError as exc:
        return _fail(str(exc))
    if not found:
        return _ok(found=False, voucher_number=voucher_number)
    return _ok(found=True, voucher=found)


@server.tool(description="Suggest the next free voucher number for a manually numbered type.")
def suggest_voucher_number(prefix: str, voucher_type: str = "Purchase", on_date: str = "") -> str:
    try:
        suggested, warning = _client().next_voucher_number(prefix, voucher_type, on_date or None)
    except TallyError as exc:
        return _fail(str(exc))
    return _ok(
        suggested=suggested,
        warning=warning,
        note="A suggestion, not a reservation — someone may be entering vouchers right now.",
    )


# --------------------------------------------------------------------- write


@server.tool(
    description=(
        "Step 1 of 2 for writing. Resolves every name against Tally, computes "
        "the money, and returns a report plus a preparation_id. NOTHING is "
        "written to Tally by this call. Show the report to the human before "
        "calling post_voucher."
    )
)
def prepare_voucher(
    kind: str,
    voucher_number: str,
    date: str,
    party: str = "",
    item_ledger: str = "",
    lines: str = "[]",
    charges: str = "[]",
    entries: str = "[]",
    reference: str = "",
    narration: str = "",
    voucher_type: str = "",
    round_off_ledger: str = "",
    invoice_total: str = "",
) -> str:
    """kind: 'purchase', 'sales' or 'journal'. date: YYYYMMDD.

    lines:   JSON list of {item, qty, rate} or {item, qty, unit_cost, currency_rate}
    charges: JSON list of {ledger, amount}
    entries: JSON list of {ledger, amount, side} — journal only, side is debit/credit
    """
    import warnings

    try:
        parsed_lines = [Line(**line) for line in json.loads(lines or "[]")]
        parsed_charges = [Charge(**charge) for charge in json.loads(charges or "[]")]
        parsed_entries = [Entry(**entry) for entry in json.loads(entries or "[]")]
    except (ValueError, TypeError) as exc:
        return _fail(f"Could not read the line/charge/entry JSON: {exc}")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if kind == "journal":
                voucher = Voucher.journal(
                    voucher_number=voucher_number,
                    date=date,
                    entries=parsed_entries,
                    voucher_type=voucher_type or "Journal",
                    narration=narration,
                    reference=reference,
                )
            else:
                builder = Voucher.purchase if kind == "purchase" else Voucher.sales
                voucher = builder(
                    voucher_number=voucher_number,
                    date=date,
                    party=party,
                    item_ledger=item_ledger,
                    lines=parsed_lines,
                    charges=parsed_charges,
                    voucher_type=voucher_type or kind.capitalize(),
                    reference=reference,
                    narration=narration,
                    round_off_ledger=round_off_ledger or None,
                    invoice_total=invoice_total or None,
                )
    except (TypeError, ValueError) as exc:
        return _fail(f"Could not build the voucher: {exc}")

    try:
        preparation = _client().prepare(voucher)
    except GateError as exc:
        return _fail(
            str(exc),
            written=False,
            advice=(
                "Nothing was written. Do not retry with a guessed name — use "
                "resolve_name, or ask the human to create the master in Tally."
            ),
        )
    except TallyError as exc:
        return _fail(str(exc), written=False)

    preparation_id = uuid.uuid4().hex[:12]
    _prepared[preparation_id] = preparation
    unverified = kind in ("sales", "journal")
    return _ok(
        preparation_id=preparation_id,
        written=False,
        report=preparation.report,
        totals=preparation.totals,
        maturity=(
            "This voucher type has not been verified against a real Tally voucher. "
            "Post to a test company first." if unverified else "verified"
        ),
        next_step=(
            "Show this report to the human. If they approve, call "
            f"post_voucher(preparation_id='{preparation_id}')."
        ),
    )


@server.tool(
    description=(
        "Step 2 of 2. Writes a voucher that already passed prepare_voucher, then "
        "reads it back out of Tally and compares. Only report success to the user "
        "if 'differences' comes back empty."
    )
)
def post_voucher(preparation_id: str) -> str:
    if not _writes_allowed():
        return _fail(
            "Writes are disabled. This server refuses to write unless "
            "TALLY_AIAGENT_ALLOW_WRITES=1 is set in its environment. Ask the "
            "human to enable it deliberately.",
            written=False,
        )
    preparation = _prepared.get(preparation_id)
    if preparation is None:
        return _fail(
            "No such preparation_id. Call prepare_voucher first — a voucher "
            "cannot be posted without passing the gate.",
            written=False,
        )
    try:
        result = _client().post(preparation, verify="warn")
    except TallyError as exc:
        return _fail(str(exc), written=False)

    _prepared.pop(preparation_id, None)
    result.pop("_raw", None)
    differences = result.get("differences", [])
    return _ok(
        written=bool(result.get("posted")),
        voucher_number=preparation.voucher.voucher_number,
        guid=result.get("guid"),
        differences=differences,
        verdict=(
            "Tally stored exactly what was sent."
            if result.get("posted") and not differences
            else "MISMATCH — the voucher exists in Tally but does not match what "
            "was sent. Tell the human immediately; nothing has been rolled back."
            if result.get("posted")
            else "Not written — Tally rejected the import."
        ),
        tally_counters={k: v for k, v in result.items() if k in ("created", "altered", "errors",
                                                                "exceptions", "ignored")},
        line_errors=result.get("lineerrors"),
    )


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

"""Command line interface.

`tally-aiagent check` is the first thing to run: it proves the connection works
and tells you what Tally actually holds, before any code of yours depends on it.
"""
import json
import os
import pathlib
import sys

import click

from . import __version__
from . import discovery
from .errors import GateError, TallyError
from .vouchers import Charge, Entry, Line, Voucher


def _client():
    from .client import Tally

    try:
        return Tally.from_env()
    except TallyError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group()
@click.version_option(__version__, prog_name="tally-aiagent")
def main():
    """Read and write Tally Prime safely — names are always Tally's own."""




def _shell_quote(value: str) -> str:
    """Quote a value so the file can be sourced by a shell.

    Company names routinely contain spaces and brackets — "Acme Traders (Pune)" —
    and an unquoted line like that is a syntax error the moment anyone runs
    `. .env`. Single quotes, with the standard escape for an embedded one.
    """
    return "'" + str(value).replace("'", "'\\''") + "'"

HELP_UNREACHABLE = """
Nothing answered at {url}.

The usual reasons, most common first:

  1. Tally isn't running, or no company is open.
     Open Tally and load your company, then try again.

  2. Tally isn't set to answer requests. In Tally:
       F1  ->  Settings  ->  Connectivity  ->  Client/Server configuration
       set  "TallyPrime acts as"  to  "Both"
     Note the port shown there — it may not be {port}.

  3. Wrong address. If Tally runs on another computer on your network, use that
     computer's IP (e.g. 192.168.1.5), not "localhost".

  4. A firewall is in the way, or your cloud Tally provider hasn't opened the port
     for you. Providers usually have to enable it on request.
"""


@main.command()
@click.option("--env-file", default=".env", show_default=True,
              help="Where to save the settings.")
def setup(env_file):
    """Set this up step by step — start here."""
    click.echo()
    click.secho("  tally-aiagent setup", bold=True)
    click.echo("  Four short steps. Nothing is written to Tally at any point.\n")

    # ---------------------------------------------------------------- step 1
    click.secho("  Step 1 of 4 — before we start", bold=True)
    click.echo("""
  Three things need to be true. Tick them off in Tally first:

    1. Tally Prime is installed and RUNNING.
    2. Your company is CREATED and OPEN in it.
       (This tool never creates a company. It reads the one you have.)
    3. Tally is set to answer requests:
         F1 -> Settings -> Connectivity -> Client/Server configuration
         set "TallyPrime acts as" to "Both", and note the port.
""")
    if not click.confirm("  All three done?", default=True):
        click.echo("\n  No problem — do those, then run `tally-aiagent setup` again.\n")
        return

    # ---------------------------------------------------------------- step 2
    click.echo()
    click.secho("  Step 2 of 4 — where is Tally?", bold=True)
    click.echo("""
    1) On this computer, or another computer in our office
    2) On a cloud Tally service (someone hosts Tally for us)
""")
    where = click.prompt("  Which one", type=click.Choice(["1", "2"]), default="1",
                         show_choices=False)

    if where == "1":
        click.echo("\n  If Tally runs on THIS computer, keep 'localhost'.")
        click.echo("  If it runs on another computer here, put that computer's IP address.")
        host = click.prompt("  Address", default="localhost")
        default_port = discovery.DEFAULT_PORT
    else:
        click.echo("\n  Your provider gave you an address — something like")
        click.echo("  yourcompany.tallycloud.in. Use that, without http:// in front.")
        host = click.prompt("  Address")
        default_port = discovery.CLOUD_PORT
        click.echo("\n  Cloud Tally usually answers on 9008 rather than 9000.")

    click.echo("\n  The port is the number shown on that Tally connectivity screen.")
    port = click.prompt("  Port", default=default_port, type=int)

    click.echo(f"\n  Trying {host}:{port} ...")
    ok, message = discovery.reachable(host, port)
    if not ok:
        click.secho(f"  Could not reach it — {message}", fg="red")
        click.echo(HELP_UNREACHABLE.format(url=f"http://{host}:{port}", port=port))
        raise SystemExit(1)
    click.secho("  Tally answered.", fg="green")

    # ---------------------------------------------------------------- step 3
    click.echo()
    click.secho("  Step 3 of 4 — which company?", bold=True)
    user = password = ""
    companies = []
    try:
        companies = discovery.companies(host, port)
    except Exception:
        companies = []

    if not companies:
        click.echo("""
  Tally answered but didn't list a company. That usually means one of two things:
  no company is open, or your company asks for a username and password.
""")
        if click.confirm("  Does your company ask for a sign-in?", default=False):
            user = click.prompt("  Tally username")
            password = click.prompt("  Tally password", hide_input=True)
            try:
                companies = discovery.companies(host, port, user, password)
            except Exception:
                companies = []

    if not companies:
        click.secho("\n  No company is open in Tally.", fg="yellow")
        click.echo("  Open the one you want in Tally, then run setup again.\n")
        raise SystemExit(1)

    if len(companies) == 1:
        company = companies[0]
        click.echo(f"\n  Found one company open:  {company}")
        if not click.confirm("  Use this one?", default=True):
            company = click.prompt("  Type the company name exactly as Tally spells it")
    else:
        click.echo("\n  These companies are open in Tally:\n")
        for i, name in enumerate(companies, 1):
            click.echo(f"    {i}) {name}")
        choice = click.prompt("\n  Which one", type=click.IntRange(1, len(companies)))
        company = companies[choice - 1]
    click.secho(f"  Using: {company}", fg="green")

    # ---------------------------------------------------------------- step 4
    click.echo()
    click.secho("  Step 4 of 4 — checking it really works", bold=True)
    from .client import Tally

    while True:
        try:
            tally = Tally(host=host, company=company, port=port, user=user, password=password)
            masters = tally.masters()
            break
        except TallyError as exc:
            click.secho(f"\n  Couldn't read from Tally: {exc}", fg="red")
            if user or not click.confirm("\n  Does your company ask for a sign-in?", default=True):
                raise SystemExit(1)
            user = click.prompt("  Tally username")
            password = click.prompt("  Tally password", hide_input=True)

    click.echo(f"\n  Read from Tally successfully:")
    click.echo(f"    {len(masters.ledgers)} ledgers (suppliers, customers, accounts)")
    click.echo(f"    {len(masters.items)} stock items")
    if not masters.ledgers and not masters.items:
        click.secho("\n  That company looks empty. Is it the right one?", fg="yellow")

    # ------------------------------------------------------------ save it
    click.echo()
    click.secho("  Saving", bold=True)
    path = pathlib.Path(env_file)
    lines = [
        "# tally-aiagent settings",
        f"TALLY_HOST={_shell_quote(host)}",
        f"TALLY_PORT={port}",
        f"TALLY_COMPANY={_shell_quote(company)}",
    ]
    if user:
        lines += [f"TALLY_USER={_shell_quote(user)}",
                  f"TALLY_PASSWORD={_shell_quote(password)}"]
    body = "\n".join(lines) + "\n"

    if path.exists():
        click.secho(f"\n  {path} already exists.", fg="yellow")
        if not click.confirm("  Add these settings to the end of it?", default=True):
            click.echo("\n  Nothing saved. Here they are to use however you like:\n")
            click.echo("".join(f"    export {l}\n" for l in lines if not l.startswith("#")))
            _show_mcp(host, port, company, user, password)
            return
        with path.open("a") as fh:
            fh.write("\n" + body)
    else:
        path.write_text(body)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    click.secho(f"  Saved to {path.resolve()} (readable only by you).", fg="green")
    if password:
        click.secho("\n  That file now holds your Tally password. Don't commit it to git.",
                    fg="yellow")

    click.echo("\n  Load it in this terminal with:")
    click.echo(f"    set -a && . {path} && set +a")

    _show_mcp(host, port, company, user, password)

    click.echo("  Try these next:\n")
    click.echo("    tally-aiagent check                      what Tally holds")
    click.echo("    tally-aiagent resolve \"a supplier name\"   is this name safe to write?")
    click.echo("    tally-aiagent masters --kind ledgers      every name Tally has\n")


def _show_mcp(host, port, company, user, password):
    """Print a ready-to-paste MCP block for Claude Code / Claude Desktop / Cursor."""
    env = {"TALLY_HOST": host, "TALLY_PORT": str(port), "TALLY_COMPANY": company}
    if user:
        env["TALLY_USER"] = user
        env["TALLY_PASSWORD"] = "<your password>"
    block = json.dumps(
        {"mcpServers": {"tally": {"command": "tally-aiagent-mcp", "env": env}}}, indent=2
    )
    click.echo("\n  To use this with an AI assistant, install the MCP extra:\n")
    click.echo("    pip install \"tally-aiagent[mcp]\"\n")
    click.echo("  then put this in your MCP config (.mcp.json, or your client's settings):\n")
    for line in block.splitlines():
        click.echo(f"    {line}")
    click.echo("""
  Writing is OFF until you add this line to that "env" block:

      "TALLY_AIAGENT_ALLOW_WRITES": "1"

  Leave it out at first. The assistant can read, and can check names, but
  cannot change your books.
""")

@main.command()
def check():
    """Prove the connection works and show what Tally holds."""
    tally = _client()
    click.echo(f"connecting to {tally.config.url}  company={tally.config.company!r}")
    try:
        masters = tally.masters()
    except TallyError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"  {len(masters.items)} stock items")
    click.echo(f"  {len(masters.ledgers)} ledgers")
    try:
        stock = tally.stock_summary()
        click.echo(f"  {len(stock)} items with stock on hand")
    except TallyError as exc:
        click.echo(f"  stock summary unavailable: {exc}")
    click.secho("connection ok", fg="green")


@main.command()
@click.option("--kind", type=click.Choice(["ledgers", "items"]), default="ledgers")
@click.option("--search", default="", help="Substring filter.")
@click.option("--limit", default=50, show_default=True)
def masters(kind, search, limit):
    """List the master names Tally holds."""
    tally = _client()
    table = tally.masters().items if kind == "items" else tally.masters().ledgers
    names = sorted(n for n in table if search.lower() in n.lower())
    for name in names[:limit]:
        click.echo(name)
    if len(names) > limit:
        click.echo(f"... and {len(names) - limit} more", err=True)


@main.command()
@click.argument("name")
@click.option("--kind", type=click.Choice(["ledger", "item"]), default="ledger")
def resolve(name, kind):
    """Check whether NAME can be safely written to Tally."""
    tally = _client()
    the_masters = tally.masters()
    resolved, how = (
        the_masters.resolve_item(name) if kind == "item" else the_masters.resolve_ledger(name)
    )
    if resolved:
        click.secho(f"OK  {name!r} -> {resolved!r}  [{how}]", fg="green")
        click.echo("this is the spelling that would be written")
        return
    click.secho(f"REFUSED  {how}", fg="red")
    candidates = the_masters.candidates(name, kind=kind)
    if candidates:
        click.echo("\ndid you mean:")
        for candidate in candidates:
            click.echo(f"  {candidate}")
    click.echo(
        "\nTally would NOT reject this name — it would create a new master and "
        "report success.\nFix the spelling, or create the master in Tally first."
    )
    sys.exit(1)


@main.command()
@click.argument("item", required=False)
def stock(item):
    """Closing stock, for everything or one ITEM."""
    summary = _client().stock_summary()
    if item:
        if item not in summary:
            click.secho(f"{item!r} is not reported by Tally (so: zero or negative).", fg="yellow")
            sys.exit(1)
        click.echo(f"{summary[item]:g}")
        return
    for name, qty in sorted(summary.items()):
        click.echo(f"{qty:>10g}  {name}")


@main.command()
@click.argument("voucher_number")
@click.option("--type", "voucher_type", default="Purchase", show_default=True)
@click.option("--date", "on_date", default="", help="Any YYYYMMDD in the target financial year.")
def voucher(voucher_number, voucher_type, on_date):
    """Read a voucher back out of Tally."""
    from datetime import date as _date

    found = _client().read_voucher(
        voucher_number, voucher_type, on_date or _date.today().strftime("%Y%m%d")
    )
    if not found:
        click.secho(f"{voucher_number} not found in Tally.", fg="yellow")
        sys.exit(1)
    click.echo(json.dumps(found, indent=2, default=str))


@main.command()
@click.argument("spec", type=click.File("r"))
@click.option("--post", "do_post", is_flag=True, help="Actually write it. Off by default.")
@click.option("--strict", is_flag=True, help="Fail loudly if the read-back disagrees.")
def prepare(spec, do_post, strict):
    """Gate a voucher described in a JSON file, and optionally post it.

    Without --post this only ever reads: it resolves every name, prices the
    voucher and prints what would be sent. See examples/ for the file shape.
    """
    import warnings

    data = json.load(spec)
    kind = data.pop("kind", "purchase")
    data["lines"] = [Line(**line) for line in data.get("lines", [])]
    data["charges"] = [Charge(**charge) for charge in data.get("charges", [])]
    entries = [Entry(**entry) for entry in data.pop("entries", [])]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if kind == "journal":
            data.pop("lines", None), data.pop("charges", None)
            built = Voucher.journal(entries=entries, **data)
        elif kind == "sales":
            built = Voucher.sales(**data)
        else:
            built = Voucher.purchase(**data)

    tally = _client()
    try:
        preparation = tally.prepare(built)
    except GateError as exc:
        click.secho(str(exc), fg="red")
        click.echo("\nNothing was sent to Tally.")
        sys.exit(1)

    click.echo(preparation.as_text())
    if not do_post:
        click.secho("\ndry run — nothing was written. Add --post to write it.", fg="yellow")
        return

    if kind in ("sales", "journal"):
        click.secho(
            f"\n{kind}() has not been verified against a real Tally voucher.", fg="yellow"
        )
        click.confirm("Post it anyway?", abort=True)

    result = tally.post(preparation, verify="strict" if strict else "warn")
    if not result.get("posted"):
        click.secho("NOT WRITTEN — Tally rejected the import.", fg="red")
        for error in result.get("lineerrors", []):
            click.echo(f"  {error}")
        sys.exit(1)
    if result["differences"]:
        click.secho("\nWRITTEN, BUT THE READ-BACK DISAGREES:", fg="red")
        for difference in result["differences"]:
            click.echo(f"  - {difference}")
        click.echo("\nThe voucher exists in Tally. Nothing was rolled back. Check the books.")
        sys.exit(1)
    click.secho(f"\nposted and verified — {built.voucher_number}  guid={result.get('guid')}",
                fg="green")


if __name__ == "__main__":
    main()

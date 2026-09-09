"""Command line interface.

`tally-aiagent check` is the first thing to run: it proves the connection works
and tells you what Tally actually holds, before any code of yours depends on it.
"""
import json
import sys

import click

from . import __version__
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

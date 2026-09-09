# Example vouchers

Each file is a voucher description. Gate one without writing anything:

```bash
tally-aiagent prepare examples/purchase.json
```

That resolves every name against your Tally, prices the voucher, and prints
what *would* be sent. Add `--post` to actually write it.

**The ledger and item names in these files are placeholders.** Replace them
with the names your own Tally holds — `tally-aiagent masters --kind ledgers`
lists them. There are deliberately no default ledger names anywhere in this
library: a plausible-looking default is the kind of thing that gets posted for
months before anyone notices it was wrong.

| File | What it shows |
|---|---|
| `purchase.json` | A supplier bill with freight and a total pinned to the supplier's invoice |
| `purchase_foreign_currency.json` | An import priced in another currency — rate is rounded before multiplying |
| `journal.json` | A two-sided journal entry with no inventory |

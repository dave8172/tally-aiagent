# tally-aiagent

**Let an AI agent write to Tally without quietly wrecking your books.**

Tally has a habit that is fine when a person is typing and dangerous when software
isn't: if you send it a supplier or product name it doesn't recognise, it doesn't
complain — it creates a new one and reports success.

This library refuses to write any name that isn't already in Tally. And after every
entry it makes, it reads the entry back out of Tally to check that what got saved is
what you meant.

---

## The problem, in one story

Your system knows a supplier as **`ACME SUPPLIES CO. LTD`**.

Tally knows the same supplier as **`ACME SUPPLIES CO LTD`** — no full stop after `CO`.

You post a purchase bill. Tally doesn't complain. It quietly opens a *second* supplier
account with the slightly different name, books the bill against it, and reports
success.

Nothing failed. No error appeared. But from that moment:

- the supplier's balance is split across two accounts, so neither is right
- your payables report understates what you owe
- statements you send that supplier don't reconcile
- and nobody finds out until someone chases a payment, weeks later

A trailing space does this. A comma does this. So does an invisible character pasted
out of Excel. The same thing happens to product names, and there it quietly changes
your stock valuation too.

This is normal Tally behaviour, not a rare bug. It's survivable when a person is
typing, because they notice the new name appear in the dropdown. It is **not**
survivable when software writes the entry — and it's worse with an AI agent, which
will confidently produce a plausible-looking name it never checked.

## What this does about it

Three rules, built into the code rather than written in a manual:

1. **Names come from Tally, not from you.** Your system supplies quantities, rates,
   dates and invoice numbers. Tally supplies names. If a name can't be found in Tally,
   the whole entry is refused and nothing is sent.
2. **When in doubt, it stops.** If your `PSU-500` could mean either `PSU 500H` or
   `PSU 500S`, there's no safe answer. It shows you both and refuses to guess.
3. **"Success" isn't proof.** After writing, it reads the entry back out of Tally and
   compares. A mismatch is reported loudly instead of being swallowed.

## Who it's for

- You're connecting Tally to an AI assistant and want a seatbelt on it.
- You're writing software that posts into Tally and don't want to discover this
  problem the way everyone else does.
- You're an accountant or business owner being asked to allow either of the above,
  and you want to know what stops it going wrong.

---

## How an agent actually uses it

Writing is deliberately **two steps, not one**. An agent can't skip the first.

**Step 1 — it prepares.** The agent describes the entry it wants to make. The library
checks every name against Tally, works out the money, and hands back a plain report.
**Nothing has been written at this point.**

```
party    'acme supplies pvt ltd' -> 'Acme Supplies Pvt Ltd'  [matched]
ledger   'Purchase Accounts' -> 'Purchase Accounts'  [exact]
item     'Widget A' -> 'Widget A'  [exact]  10 x 125.50 = 1255.00
charge   'Freight Inward' -> 'Freight Inward'  [exact]  450.00
totals   goods=1255.00  charges=450.00  party=1705.00
```

That report is the thing a human reads. Left column: what the agent asked for. Right
column: what Tally actually holds. Bottom: the money.

**Step 2 — you approve, it posts.** Only then does anything reach Tally, and
immediately afterwards the entry is read back and compared.

The reason an agent can't skip step 1 is structural, not a rule it's asked to follow:
the "post" tool takes only a reference to something that already passed step 1. It has
no way to describe a voucher at all. So there is always a report, and it is always
readable.

If a name doesn't check out, the agent gets this instead — and no entry is created:

```
REFUSED  no ledger in Tally matches 'Acme Supplies Co. Ltd'

did you mean:
  Acme Supplies Pvt Ltd

Tally would NOT reject this name — it would create a new account and report success.
```

---

## Get started

**1. Install it**

```bash
pip install tally-aiagent
```

**2. Let Tally answer requests.** In Tally: **F1 → Settings → Connectivity →
Client/Server configuration**, and set *TallyPrime acts as* to **Both**. Note the port
(9000 by default). Tally must be running with your company open.

**3. Tell it where Tally is**

```bash
export TALLY_HOST=localhost            # the machine Tally runs on
export TALLY_PORT=9000                 # often 9008 on hosted Tally
export TALLY_COMPANY="Your Company"    # exactly as spelled in Tally
```

**4. Check it works**

```bash
tally-aiagent check
```

```
connecting to http://localhost:9000  company='Your Company'
  240 stock items
  519 ledgers
  170 items with stock on hand
connection ok
```

**5. Try the bit that matters** — ask whether a name is safe to write:

```bash
tally-aiagent resolve "acme supplies pvt. ltd."
```

```
OK  'acme supplies pvt. ltd.' -> 'Acme Supplies Pvt Ltd'  [matched]
this is the spelling that would be written
```

---

## Connect it to an AI agent

```bash
pip install "tally-aiagent[mcp]"
```

It speaks [MCP](https://modelcontextprotocol.io), so it works with Claude Code, Claude
Desktop, Cursor, or anything else that speaks MCP. Add this to your MCP config
(`.mcp.json`, or your client's settings):

```json
{
  "mcpServers": {
    "tally": {
      "command": "tally-aiagent-mcp",
      "env": {
        "TALLY_HOST": "localhost",
        "TALLY_COMPANY": "Your Company",
        "TALLY_AIAGENT_ALLOW_WRITES": "1"
      }
    }
  }
}
```

**Writes are off until you turn them on.** Leave `TALLY_AIAGENT_ALLOW_WRITES` out
entirely and the agent can look but not touch. Start there, watch it prepare a few
entries, and turn writing on when you're comfortable.

Then you can just talk to it: *"What's our stock of Widget A?"*, *"Is 'Acme Supplies
Co Ltd' a real supplier in Tally?"*, *"Book a purchase from Acme — 10 Widget A at
125.50, invoice INV-4471."* The last one comes back as a report to approve, not as a
finished entry.

What the agent can do:

| Tool | What it does |
|---|---|
| `list_masters` | The exact supplier, customer, ledger and product names Tally holds |
| `resolve_name` | Is this name safe to write? Returns Tally's spelling, or why not |
| `stock` | Closing stock quantities |
| `read_voucher` | Read an entry back out of the books |
| `suggest_voucher_number` | The next free number for a manually numbered voucher type |
| `prepare_voucher` | **Step 1** — check and price it. Writes nothing |
| `post_voucher` | **Step 2** — write something that already passed step 1, then verify it |

---

## From the command line

```bash
tally-aiagent check                          # connection and what Tally holds
tally-aiagent masters --kind ledgers         # every ledger name
tally-aiagent masters --kind items --search widget
tally-aiagent resolve "some supplier name"   # is this safe to write?
tally-aiagent stock                          # closing stock
tally-aiagent stock "Widget A"
tally-aiagent voucher PUR-001/2627           # read an entry back
tally-aiagent prepare entry.json             # dry run — writes nothing
tally-aiagent prepare entry.json --post      # write it, then verify
```

## Examples

An entry is a small JSON file. More in [`examples/`](examples/).

**A purchase bill:**

```json
{
  "kind": "purchase",
  "voucher_number": "PUR-001/2627",
  "date": "20260909",
  "party": "Acme Supplies Pvt Ltd",
  "item_ledger": "Purchase Accounts",
  "reference": "INV-4471",
  "lines": [
    { "item": "Widget A", "qty": 10, "rate": "125.50" }
  ],
  "charges": [
    { "ledger": "Freight Inward", "amount": "450.00" }
  ]
}
```

**Buying in another currency** — give the foreign price and the rate:

```json
{ "item": "Widget A", "qty": 50, "unit_cost": "10.25", "currency_rate": "88.40" }
```

**A journal entry:**

```json
{
  "kind": "journal",
  "voucher_number": "JV-007/2627",
  "date": "20260909",
  "entries": [
    { "ledger": "Freight Inward", "amount": "450.00", "side": "debit"  },
    { "ledger": "Bank Account",   "amount": "450.00", "side": "credit" }
  ]
}
```

Dry run first — this only reads:

```bash
tally-aiagent prepare examples/purchase.json
```

The ledger names in the examples are placeholders. Use your own — `tally-aiagent
masters --kind ledgers` lists them. **There are no default ledger names anywhere in
this library**, on purpose: a plausible-looking default gets posted for months before
anyone notices it was wrong.

---

## From Python

```python
from tally_aiagent import Tally, Voucher, Line, Charge, GateError

tally = Tally.from_env()

voucher = Voucher.purchase(
    voucher_number="PUR-001/2627",
    date="20260909",
    party="acme supplies pvt ltd",          # your spelling
    item_ledger="Purchase Accounts",
    lines=[Line(item="Widget A", qty=10, rate="125.50")],
    charges=[Charge(ledger="Freight Inward", amount="450.00")],
)

try:
    preparation = tally.prepare(voucher)     # the check. sends nothing.
except GateError as exc:
    print(exc)                               # every problem, listed at once
    raise

print(preparation.as_text())                 # show a human
result = tally.post(preparation)             # writes, then reads back

if result["differences"]:
    alert(result["differences"])             # written, but not what we sent
```

`post()` accepts only what `prepare()` returns, so skipping the check means deleting
code rather than forgetting a flag.

A few details worth knowing:

- **Money is never a float.** Rates are rounded to two places *before* being multiplied
  by quantity, which is what Tally does. Rounding at the end instead disagrees by a
  paisa or two per line, and over a long invoice the total stops matching the supplier's.
- **Units come from Tally**, not from a guess, so an item measured in `Pcs` isn't
  written as `Nos`.
- **Many voucher types are auto-numbered.** Tally ignores the number you send and
  assigns its own. The library notices, reads the entry back by Tally's internal id
  instead, and tells you the number Tally used in `result["assigned_voucher_number"]`.
- **This library only ever creates.** It cannot alter or delete an entry, deliberately.
  (Deleting a voucher over Tally's XML interface is unreliable in practice — it will
  report `Voucher does not exist!` for a voucher that plainly does. Delete in Tally.)

---

## What's verified, and what isn't

This matters more here than in most libraries, because the failure mode is silent and
lands in someone's books. All of the below was checked against a real company with 240
stock items and 519 ledgers.

| | Status |
|---|---|
| Name checking, refusals, suggestions | **Verified** against real supplier names |
| Reading entries back | **Verified** against real posted vouchers |
| Money and rounding | **Verified** — reproduces a real voucher to the paisa |
| **Purchase entries** | **Verified** — generated XML is byte-identical to production |
| **Journal entries** | **Verified** — posted to a live company, read back, correct |
| **Sales entries** | **Verified structurally** — matches a real sales voucher field by field, but none has been posted |

**How.** Six real supplier names were checked, four of which differ from Tally's own
spelling by punctuation or case; all six resolved to Tally's spelling, and a near-miss
Tally doesn't hold was refused with the right name suggested. A real 75-line purchase
voucher was read back and matched an independent implementation exactly. The generated
purchase envelope was diffed against the bytes a production system actually posts:
**37,467 bytes, byte-for-byte identical**. A journal entry was posted live, read back,
and deleted. A real sales voucher was rebuilt through the library and compared field by
field — item, quantity, rate, amounts, both sign conventions, party flags — all matching.

Two things that only showed up against a live company, both now fixed and covered by
tests:

- **Journal entries need `ALLLEDGERENTRIES.LIST`** — three Ls — not the
  `LEDGERENTRIES.LIST` an invoice uses. Send the wrong one and Tally doesn't report a
  line error; it returns `EXCEPTIONS=1` with no message at all and creates nothing.
- **Auto-numbered voucher types** broke reading back by number, as described above.

Sales is the one gap: the shape matches a real voucher exactly, but a shape that matches
is not the same as an entry Tally accepted. **Post one to a test company first and read
the verification output** — which is what the read-back check is for. If you do, a PR
confirming or correcting it is the most useful thing this repo can receive.

## Security

Tally's HTTP interface **has no encryption**. Tally doesn't support HTTPS on that port,
so the username and password travel in clear text.

- Keep this on a local network, a VPN, or an SSH tunnel. **Never expose Tally's port to
  the internet.**
- Prepared entries contain no credentials — they're added only at the moment of sending
  — so a report is safe to log or show an agent.
- The MCP server refuses to write unless `TALLY_AIAGENT_ALLOW_WRITES=1`.
- This is not a substitute for Tally's own user permissions. Give the account it uses
  only the rights it needs.

**On agents specifically:** an approval step stops being oversight when someone is
clicking through fifty of them an hour. Keep the volume low enough that the report gets
read, and treat the read-back result as the real safety net.

### Settings reference

| Variable | Needed | Notes |
|---|---|---|
| `TALLY_HOST` | yes | Machine running Tally, e.g. `localhost` |
| `TALLY_COMPANY` | yes | Exactly as spelled in Tally's company list |
| `TALLY_PORT` | no | Defaults to `9000`; hosted Tally is often `9008` |
| `TALLY_USER` | no | Only if your company has user security enabled |
| `TALLY_PASSWORD` | no | As above |
| `TALLY_AIAGENT_ALLOW_WRITES` | no | MCP server only. `1` to permit writing |

---

## Why this exists

It came out of a working system, not a whiteboard. A hardware distributor's internal
tool needed to post supplier bills into Tally, and the first attempt did what every
guide shows: build the XML, send the names from the database, check that Tally said
`CREATED=1`.

All three supplier names in that database differed from Tally's by punctuation. Posting
would have created three duplicate supplier accounts, silently, and the books would have
looked fine.

The fix is the rule at the top of this file: reads may come from your tool, writes must
come from Tally. This library is that rule, extracted.

The wider point isn't really about Tally. Most of the current conversation about agent
safety is about *permissions* — what an agent is allowed to touch — and *data* — what it
might leak. Neither catches this. The write here is authorised, permitted, in scope and
fully audited. It's simply **wrong**, in a way no approval prompt would reveal, because
the entry looks perfectly correct on screen. Correctness needs its own guardrails, and
they have to be built from knowing how the specific system fails.

## Contributing

Useful, roughly in order:

1. Post a sales entry against a real Tally and report what differs.
2. Voucher types this doesn't cover yet — receipt, payment, contra, debit/credit note.
3. Failure modes you've hit that the checks don't catch.

```bash
pip install -e ".[dev]" && pytest
```

The tests run against a fake Tally, so you don't need Tally installed to work on this.

## License

MIT. Not affiliated with or endorsed by Tally Solutions Pvt. Ltd.

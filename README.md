# tally-aiagent

**Safe writes to Tally Prime, for AI agents and the people who have to trust them.**

Tally does not reject a supplier or product name it has never seen. It *creates* one,
posts your entry against it, and reports success. This library refuses to write any
name that is not already in Tally's own master list — and after every write, it reads
the voucher back out of Tally to check that what got stored is what you sent.

---

## The problem, in one story

Your system knows a supplier as **`ACME SUPPLIES CO. LTD`**.

Tally knows the same supplier as **`ACME SUPPLIES CO LTD`** — no full stop after `CO`.

You post a purchase bill. Tally does not complain. It quietly opens a *second* supplier
ledger with the slightly different name, books the bill against it, and returns success.

Nothing failed. No error appeared. But from that moment:

- the supplier's outstanding balance is split across two ledgers, so neither is right
- the payables report understates what you owe
- statements sent to that supplier don't reconcile
- and nobody finds out until someone chases a payment, weeks later

A trailing space does this. A comma does this. So does an invisible character pasted out
of Excel. The same thing happens to product names, and there it silently changes your
stock valuation too.

**This is not a rare edge case — it is Tally's normal, documented behaviour on import.**
It is survivable when a human is typing, because a human notices the new name appear in
the dropdown. It is *not* survivable when software writes the entry, and it is much worse
when an AI agent does, because an agent will confidently produce a plausible-looking name
it has never verified.

## What this does about it

```
Your system  ─────►  the gate  ─────►  Tally
              names         only names Tally
              you have      already holds
```

Three rules, enforced in code rather than in documentation:

1. **Every name written into a voucher comes out of Tally's own master export.** Your
   system supplies quantities, rates, dates and references. Tally supplies names. If a
   name cannot be found, the whole voucher is refused and nothing is sent.
2. **Ambiguity is a refusal, not a guess.** If your `PSU-500` matches both `PSU 500H`
   and `PSU 500S`, there is no safe answer. It shows you both and stops.
3. **`CREATED=1` is not proof.** After every write, the voucher is read back out of
   Tally and compared against what was intended. A mismatch is reported loudly, not
   swallowed.

---

## Try it in 60 seconds

```bash
pip install tally-aiagent

export TALLY_HOST=localhost          # the machine Tally runs on
export TALLY_PORT=9000               # 9000 by default; often 9008 on hosted Tally
export TALLY_COMPANY="Your Company"  # exactly as spelled in Tally

tally-aiagent check
```

```
connecting to http://localhost:9000  company='Your Company'
  240 stock items
  1,118 ledgers
  186 items with stock on hand
connection ok
```

Now ask it about a name before anything depends on it:

```bash
tally-aiagent resolve "acme supplies pvt. ltd."
```

```
OK  'acme supplies pvt. ltd.' -> 'Acme Supplies Pvt Ltd'  [normalized ('acme supplies pvt. ltd.' -> 'Acme Supplies Pvt Ltd')]
this is the spelling that would be written
```

And a name Tally does not have:

```bash
tally-aiagent resolve "Acme Supplies Co. Ltd"
```

```
REFUSED  no ledger in Tally matches 'Acme Supplies Co. Ltd'

did you mean:
  Acme Supplies Pvt Ltd

Tally would NOT reject this name — it would create a new master and report success.
Fix the spelling, or create the master in Tally first.
```

That second output is the entire product. Everything else is plumbing around it.

---

## Post a voucher

Describe it in a JSON file — see [`examples/`](examples/) for more:

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

Dry run first — this reads from Tally and writes nothing:

```bash
tally-aiagent prepare examples/purchase.json
```

```
party    'Acme Supplies Pvt Ltd' -> 'Acme Supplies Pvt Ltd'  [exact]
ledger   'Purchase Accounts' -> 'Purchase Accounts'  [exact]
item     'Widget A' -> 'Widget A'  [exact]  10 x 125.50 = 1255.00
charge   'Freight Inward' -> 'Freight Inward'  [exact]  450.00
totals   goods=1255.00  charges=450.00  round_off=0.00  party=1705.00

dry run — nothing was written. Add --post to write it.
```

Then write it:

```bash
tally-aiagent prepare examples/purchase.json --post
```

```
posted and verified — PUR-001/2627  guid=8f2c1a...-0004
```

"Verified" there is doing real work: the voucher was read back out of Tally and its
totals, line count and party name matched what was sent.

---

## In Python

```python
from tally_aiagent import Tally, Voucher, Line, Charge, GateError

tally = Tally.from_env()

voucher = Voucher.purchase(
    voucher_number="PUR-001/2627",
    date="20260909",
    party="acme supplies pvt ltd",        # your spelling
    item_ledger="Purchase Accounts",
    lines=[Line(item="Widget A", qty=10, rate="125.50")],
    charges=[Charge(ledger="Freight Inward", amount="450.00")],
)

try:
    preparation = tally.prepare(voucher)   # the gate. sends nothing.
except GateError as exc:
    print(exc)                             # every problem, listed at once
    raise

print(preparation.as_text())               # show a human before writing
result = tally.post(preparation)           # writes, then reads back

if result["differences"]:
    alert(result["differences"])           # written, but not what we sent
```

**You cannot post a voucher that was not prepared.** `post()` accepts only the object
`prepare()` returns, so skipping the gate requires deleting code rather than forgetting
a flag.

### Buying in another currency

Give `unit_cost` and `currency_rate` instead of `rate`:

```python
Line(item="Widget A", qty=50, unit_cost="10.25", currency_rate="88.40")
```

The rate is rounded to two places *before* being multiplied by the quantity, which is
what Tally itself does. Rounding at the end instead disagrees by a paisa or two per
line, and on a long voucher the party total stops matching the supplier's invoice.

---

## MCP server (for AI agents)

```bash
pip install "tally-aiagent[mcp]"
```

Point an MCP client at the `tally-aiagent-mcp` command over stdio. For Claude Code or
Claude Desktop, in `.mcp.json`:

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

**Writes are off unless you turn them on.** Without `TALLY_AIAGENT_ALLOW_WRITES=1` the
server reads and gates, and refuses to post. Leave it off until you have watched it
prepare a few vouchers.

| Tool | What it does |
|---|---|
| `list_masters` | The exact ledger or stock item names Tally holds |
| `resolve_name` | Can this name be safely written? Returns Tally's spelling, or why not |
| `stock` | Closing quantities |
| `read_voucher` | Read a voucher back out of the books |
| `suggest_voucher_number` | Next free number for a manually numbered voucher type |
| `prepare_voucher` | **Step 1 of 2** — gate and price it. Writes nothing. Returns a report and an id |
| `post_voucher` | **Step 2 of 2** — write a voucher that already passed the gate, then verify it |

The write path is two calls on purpose. `post_voucher` takes only a `preparation_id` —
it has no way to express a voucher — so an agent physically cannot write without first
producing a report a human can read. That report is the approval gate, and it is
legible: names on the left, Tally's names on the right, money at the bottom.

---

## What is verified, and what is not

Being honest about this matters more here than in most libraries, because the failure
mode is silent and lands in someone's books.

| | Status |
|---|---|
| The gate, name resolution, ambiguity refusal | **Verified against a live company** |
| Read-back verification | **Verified against a real posted voucher** |
| Money and rounding | **Verified — reproduces a real voucher to the paisa** |
| **Purchase vouchers** | **Verified — generated XML is byte-identical to production** |
| **Sales vouchers** | **Not yet verified** against a real Tally sales voucher |
| **Journal vouchers** | **Not yet verified** against a real Tally journal voucher |

### How the purchase path was verified

Against a live company with 240 stock items and 519 ledgers, without writing anything
to it:

- **Name resolution** was run over six real supplier names, four of which differed from
  Tally's own spelling by punctuation or case (`WILSONIC DEVELOPMENT CO. LTD` against
  Tally's `WILSONIC DEVELOPMENT CO LTD`, and similar). All six resolved to Tally's
  spelling. A near-miss that Tally does *not* hold — `Technologies` where the master
  says `Technology` — was refused, with the correct name offered as a suggestion.
- **Read-back** was run against a real posted 75-line purchase voucher. The parsed
  totals matched an independent production implementation exactly.
- **The write path** was checked by generating the envelope for that same voucher and
  diffing it against the bytes a production system actually posts. **37,467 bytes,
  byte-for-byte identical** — so the bytes this library would send are the bytes that
  system already posts successfully.

That last check is why no test voucher had to be created in a live company to trust the
purchase path. It is also why voucher element order here follows a proven sequence
rather than a tidier one: Tally appears to parse these header fields by name rather than
position, but "appears to" is not a reason to reorder working XML.

Sales and journal follow Tally's documented voucher shape and are covered by tests, but
"passes its tests" is not "matches what Tally stores". Both emit a warning when used.
**Post one to a test company first and read the verification output** — which is exactly
what the read-back check is for.

If you verify one against a real voucher, a PR correcting or confirming the shape is the
single most useful contribution this repo can receive.

---

## Security

Tally's HTTP interface **has no TLS**. Tally does not support HTTPS on that port, so the
username and password travel in clear text inside the request body.

- Keep this on a LAN, a VPN or an SSH tunnel. **Never expose Tally's port to the internet.**
- Prepared voucher XML deliberately contains no credentials — they are added only at send
  time — so a preparation report is safe to log, diff, or hand to an agent.
- The MCP server refuses writes unless `TALLY_AIAGENT_ALLOW_WRITES=1`.
- Nothing here is a substitute for Tally's own user permissions. Give the account this
  library uses only the rights it needs.

**On agents specifically:** an approval gate stops being oversight when a human is
clicking through fifty of them a session. Keep the volume low enough that the report is
actually read, and treat the read-back `differences` as the real safety net.

---

## Setting up Tally

Tally must be running, with the company open, and configured to answer on its port:

> **F1 → Settings → Connectivity → Client/Server configuration**
> Set *TallyPrime acts as* to **Both**, and note the port (9000 by default).

Environment variables:

| Variable | Needed | Notes |
|---|---|---|
| `TALLY_HOST` | yes | Machine running Tally, e.g. `localhost` |
| `TALLY_COMPANY` | yes | Exactly as spelled in Tally's company list |
| `TALLY_PORT` | no | Defaults to `9000`; hosted Tally is often `9008` |
| `TALLY_USER` | no | Only if your company has user security enabled |
| `TALLY_PASSWORD` | no | As above |
| `TALLY_AIAGENT_ALLOW_WRITES` | no | MCP server only. `1` to permit writes |

---

## Why this exists

It came out of a working system, not a whiteboard. A hardware distributor's internal
tool needed to post import purchase vouchers into Tally, and the first attempt did what
every guide shows: build the XML, send the names from the database, check `CREATED=1`.

All three supplier names in that database differed from Tally's by punctuation. Posting
would have created three duplicate supplier ledgers, silently, and the books would have
looked fine.

The fix was the rule at the top of this file: reads may come from your tool, writes must
be Tally-sourced. This library is that rule, extracted.

The wider point generalises past Tally. The current conversation about agent safety is
mostly about *permissions* — what an agent is allowed to touch — and *data* — what it
might leak. Neither catches this. The write here is authorised, permitted, in scope, and
fully audited. It is simply **wrong**, in a way no approval prompt would reveal, because
the voucher looks perfectly correct on screen. Correctness needs its own guardrails, and
they have to be built from knowing how the specific system fails.

---

## Contributing

Useful, in rough order:

1. Verify a sales or journal voucher against a real Tally and report what differs.
2. Voucher types this does not cover yet — receipt, payment, contra, debit/credit note.
3. Failure modes you have hit that the gate does not catch.

Run the tests with `pip install -e ".[dev]" && pytest`. They use a fake Tally, so no
Tally installation is needed to work on this.

## License

MIT. Not affiliated with or endorsed by Tally Solutions Pvt. Ltd.

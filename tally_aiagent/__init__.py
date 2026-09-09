"""tally-aiagent — a safety gate for writing to Tally Prime.

Tally does not reject a master name it has never seen. It creates one. This
library refuses to write any name it cannot find in Tally's own master list,
and reads every voucher back after posting to check that Tally stored what you
meant.

    from tally_aiagent import Tally, Voucher, Line, GateError

    tally = Tally.from_env()
    voucher = Voucher.purchase(
        voucher_number="PUR-001",
        date="20260909",
        party="Acme Supplies Pvt Ltd",
        item_ledger="Purchase Accounts",
        lines=[Line(item="Widget A", qty=10, rate="125.50")],
    )

    preparation = tally.prepare(voucher)   # the gate. sends nothing.
    print(preparation.as_text())
    result = tally.post(preparation)       # writes, then verifies
"""
from .client import Tally, TallyConfig
from .errors import (
    GateError,
    NotConfigured,
    NotPrepared,
    TallyError,
    Unreachable,
    VerificationError,
)
from .masters import Masters, normalize
from .posting import Preparation
from .vouchers import Charge, Entry, Line, Voucher

__version__ = "0.2.0"

__all__ = [
    "Tally",
    "TallyConfig",
    "Voucher",
    "Line",
    "Charge",
    "Entry",
    "Masters",
    "Preparation",
    "normalize",
    "TallyError",
    "GateError",
    "NotConfigured",
    "NotPrepared",
    "Unreachable",
    "VerificationError",
    "__version__",
]

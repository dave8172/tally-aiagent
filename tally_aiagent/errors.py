"""Exceptions. Every one of these means *nothing was written to Tally*."""


class TallyError(RuntimeError):
    """Base class. Something went wrong talking to Tally."""


class NotConfigured(TallyError):
    """No host/company configured — see Tally.from_env()."""


class Unreachable(TallyError):
    """Tally did not answer. Reads fail open, writes fail closed."""


class GateError(TallyError):
    """A name could not be sourced from Tally's own master list.

    This is the whole point of the library. Tally does not error when you send
    it a master name it does not recognise — it silently *creates* one. So a
    trailing space, a stray comma or an invisible character pasted out of Excel
    turns into a second supplier ledger nobody notices until the books are
    reconciled. Refusing the write is the only safe answer.
    """


class NotPrepared(TallyError):
    """post() was called with something that never passed the gate."""


class VerificationError(TallyError):
    """The voucher was written, but reading it back does not match what we sent.

    Raised only when post(..., verify="strict"). The voucher EXISTS in Tally —
    this is not a rollback, it is a loud alarm. Check the books.
    """

    def __init__(self, message: str, differences: list[str], voucher_number: str):
        super().__init__(message)
        self.differences = differences
        self.voucher_number = voucher_number

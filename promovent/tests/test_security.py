"""Static guarantees about the codebase."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "promovent"
CODE = {p: p.read_text() for p in SRC.rglob("*.py")}


def test_no_withdrawal_or_transfer_capability():
    pat = re.compile(r"def\s+\w*(withdraw|transfer)\w*|/(withdraw|transfer|sapi/v1/capital)", re.I)
    assert not [p for p, s in CODE.items() if pat.search(s)]


def test_no_signed_exchange_requests():
    pat = re.compile(r"hmac\.new|signature=|X-MBX-APIKEY|OK-ACCESS-SIGN|CB-ACCESS-SIGN", re.I)
    assert not [p.name for p, s in CODE.items() if pat.search(s)]


def test_no_secrets_committed():
    pat = re.compile(r"(api[_-]?key|secret)\s*=\s*['\"][A-Za-z0-9]{16,}['\"]", re.I)
    assert not [p for p, s in CODE.items() if pat.search(s)]

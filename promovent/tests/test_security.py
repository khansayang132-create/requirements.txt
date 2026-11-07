"""Static guarantees about the codebase."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "promovent"
CODE = {p: p.read_text() for p in SRC.rglob("*.py")}


def test_no_withdrawal_or_transfer_capability():
    pat = re.compile(r"def\s+\w*(withdraw|transfer)\w*|/(withdraw|transfer|sapi/v1/capital)", re.I)
    assert not [p for p, s in CODE.items() if pat.search(s)]


def test_signed_requests_only_in_execution_package():
    """V2.5: live trading signs requests, but only promovent/execution/ may do it."""
    pat = re.compile(r"hmac\.new|signature=|X-MBX-APIKEY|OK-ACCESS-SIGN|CB-ACCESS-SIGN|X-BAPI-SIGN", re.I)
    offenders = [str(p.relative_to(SRC)) for p, s in CODE.items() if pat.search(s) and p.parent.name != "execution"]
    assert offenders == []


def test_no_exchange_withdrawal_or_transfer_endpoints():
    """Every documented withdrawal / transfer / deposit-address path for the supported exchanges is banned."""
    banned = ["/sapi/v1/capital/withdraw", "/wapi/", "/sapi/v1/asset/transfer", "/sapi/v1/sub-account/transfer",
              "/v5/asset/withdraw", "/v5/asset/transfer", "/v5/asset/deposit",
              "/api/v5/asset/withdrawal", "/api/v5/asset/transfer", "/api/v5/asset/deposit-address"]
    hits = [(p.name, b) for p, s in CODE.items() for b in banned if b in s]
    assert hits == []


def test_no_secrets_committed():
    pat = re.compile(r"(api[_-]?key|secret)\s*=\s*['\"][A-Za-z0-9]{16,}['\"]", re.I)
    assert not [p for p, s in CODE.items() if pat.search(s)]

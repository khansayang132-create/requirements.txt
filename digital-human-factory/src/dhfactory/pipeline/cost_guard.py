"""No paid call happens unless (1) the job was run with --approve-spend, (2) the owner confirmed a price for that
provider in configuration/pricing.json, and (3) the estimate keeps the job under DHF_MAX_SPEND_USD.
A completed paid step is never paid for twice: its provider job id is stored and reused on resume."""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import SpendNotApproved
from ..state import ProductionState


def pricing(root: Path) -> dict:
    p = root / "configuration" / "pricing.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def price_for(root: Path, provider: str, capability: str, amount: float) -> float | None:
    entry = (pricing(root).get(provider) or {}).get(capability)
    if not entry or entry.get("usd_per_unit") is None:
        return None
    return round(float(entry["usd_per_unit"]) * amount, 4)


def authorize(state: ProductionState, provider, capability: str, amount: float, cap_usd: float) -> float:
    """Return the estimated cost when the call may go ahead; raise SpendNotApproved otherwise."""
    if not provider.paid:
        return 0.0
    est = provider.estimate_usd(capability, amount)
    if not state.spend_approved:
        raise SpendNotApproved(f"{provider.name} {capability} is paid (estimate: {f'${est:.2f}' if est is not None else 'unknown'}); "
                               f"run again with --approve-spend")
    if est is None:
        raise SpendNotApproved(f"no confirmed price for {provider.name}/{capability}: add it to configuration/pricing.json from the provider's pricing page")
    if state.spent_usd + est > cap_usd:
        raise SpendNotApproved(f"{provider.name} {capability} (${est:.2f}) would take this job past DHF_MAX_SPEND_USD (${cap_usd:.2f})")
    return est

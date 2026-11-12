from ..errors import ProviderNotConfigured, SpendNotApproved  # noqa: F401
from .base import REGISTRY, get_provider  # noqa: F401


class GatedProvider:
    """v0.3 interface: constructing an adapter fails with ProviderNotConfigured when its credential is missing."""
    provider = ""

    def __init__(self, approve_spend: bool = False, settings=None):
        from ..config import Settings

        self.approve_spend = approve_spend
        self.impl = get_provider(self.provider, settings or Settings())
        self.impl.key()

    def require_spend_approval(self):
        if not self.approve_spend:
            raise SpendNotApproved("Paid generation blocked: rerun with explicit --approve-spend after reviewing provider pricing/credits.")


class RunwayAdapter(GatedProvider): provider = "runway"
class FluxAdapter(GatedProvider): provider = "flux"
class KlingAdapter(GatedProvider): provider = "kling"
class HiggsfieldAdapter(GatedProvider): provider = "higgsfield"
class ElevenLabsAdapter(GatedProvider): provider = "elevenlabs"

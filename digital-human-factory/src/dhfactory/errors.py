"""Errors the pipeline reacts to. Each maps to a step status."""


class DHFError(Exception):
    status = "failed"


class ProviderNotConfigured(DHFError):
    """A provider's credentials (or CLI sign-in) are missing. The step is BLOCKED, never faked."""

    status = "blocked"

    def __init__(self, provider: str, needs: str):
        super().__init__(f"{provider} is not configured: {needs}")
        self.provider = provider
        self.needs = needs


class ProviderUnreachable(DHFError):
    status = "blocked"


class SpendNotApproved(DHFError):
    """A paid step was reached without --approve-spend (or it would exceed the cap)."""

    status = "blocked_pending_approval"


class ProviderError(DHFError):
    def __init__(self, provider: str, message: str, transient: bool = False):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.transient = transient


class QualityFailed(DHFError):
    pass

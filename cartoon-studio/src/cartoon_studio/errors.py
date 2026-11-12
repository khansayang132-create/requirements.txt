class StudioError(Exception):
    status = "failed"


class ProviderNotConfigured(StudioError):
    status = "blocked"

    def __init__(self, provider: str, needs: str | None = None):
        super().__init__(f"{provider} is not configured: {needs}" if needs else provider)
        self.provider, self.needs = provider, needs


class SpendNotApproved(StudioError):
    status = "blocked_pending_approval"


class ProviderError(StudioError):
    def __init__(self, provider: str, message: str, transient: bool = False):
        super().__init__(f"{provider}: {message}")
        self.transient = transient


class ConsistencyError(StudioError):
    """The character bible is missing or a reference image no longer matches its recorded hash."""

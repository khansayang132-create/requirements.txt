"""External intelligence: on-chain whale flows, news and sentiment. Each provider needs its own
API key and network access; without them the service reports exactly what is missing."""

import os


class ProviderUnavailable(RuntimeError):
    pass


def require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise ProviderUnavailable(f"missing environment variables: {', '.join(missing)}")
    return {n: os.environ[n] for n in names}

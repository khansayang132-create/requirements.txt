import json
import sys
from datetime import UTC, datetime

from .redaction import redact


def log(event: str, **fields) -> None:
    rec = {"ts": datetime.now(UTC).strftime("%H:%M:%S"), "event": event, **fields}
    print(redact(json.dumps(rec, default=str)), file=sys.stderr)

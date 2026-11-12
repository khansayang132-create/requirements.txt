# API configuration

Copy `.env.example` to `.env` and fill only the providers you have enabled. Keys are read with pydantic-settings as
secrets, are never printed, and `.env` is git-ignored. Paid steps also need `--approve-spend` on the command line and a
confirmed price in `configuration/pricing.json`. Spending stops at `CS_MAX_SPEND_USD` (default 5).

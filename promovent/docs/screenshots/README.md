# Screenshots and where they came from

| Folder | What it shows | Data |
|---|---|---|
| `v2.5-docker-production/` | All 12 pages of the V2.5 Docker stack running **in the build sandbox** with `PROMOVENT_ENV=production`, `PROMOVENT_SOURCE=live`, PostgreSQL and Redis. Captured with Playwright at 1440 and 390 px. | **No market data**: the sandbox blocks every exchange, so panels show UNAVAILABLE with the real error. This is a local run, **not a deployment**. |
| `v2.5-dev-simulated/` | Same frontend against a development backend (`PROMOVENT_SOURCE=synthetic`, auth off), used for the design check. | **SIMULATED**: generated prices; every page carries the SIMULATED banner. Not market data. |
| `v2.0-static-synthetic/` | The retired V2.0 single-page HTML terminal. | SIMULATED (generated). |

There are no screenshots of a deployed production URL because no deployment exists (TEST_REPORT.md §4).

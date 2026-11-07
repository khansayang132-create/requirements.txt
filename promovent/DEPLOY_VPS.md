# Deploying Promovent on a Linux VPS

Tested parts: the Docker images build and the full stack runs (TEST_REPORT.md). **This VPS procedure itself has not
been run by the author** (no VPS was available); follow it and check each step's verification command.

## 0. Choose the location first

Binance refuses API traffic from some countries and cloud regions (HTTP 451). Before anything else, on the VPS:

```bash
curl -s https://api.binance.com/api/v3/ping; echo        # must print {} (not a 451 "restricted location" message)
curl -s https://testnet.binance.vision/api/v3/ping; echo  # same for the spot testnet
```

Only use a VPS where both answer `{}` and where using Binance is legal for you.

## 1. Server

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git ufw
sudo ufw allow OpenSSH && sudo ufw allow 443 && sudo ufw enable   # keep 3000/8000 closed; put a TLS proxy (Caddy/nginx) in front
git clone https://github.com/khansayang132-create/requirements.txt.git promovent-src && cd promovent-src/promovent
cp .env.example .env && chmod 600 .env
```

Edit `.env`: `POSTGRES_PASSWORD`, `PROMOVENT_API_KEYS` (`python3 -c "import secrets;print(secrets.token_urlsafe(32))"`),
`PROMOVENT_EXCHANGE=binance`, `PROMOVENT_INITIAL_CAPITAL=30`, `PROMOVENT_MODE=paper`, `PROMOVENT_ENABLE_LIVE=no`.

## 2. Start and verify

```bash
docker compose up -d --build
docker compose ps                                   # 5 services "healthy"
curl -s http://127.0.0.1:8000/api/health            # database postgresql ok, redis ok, a worker heartbeat
curl -s -H "X-API-Key: <admin key>" http://127.0.0.1:8000/api/exchanges/health   # binance ok: true
curl -s -H "X-API-Key: <admin key>" http://127.0.0.1:8000/api/stream             # binance prices, CONNECTED
curl -s http://127.0.0.1:8000/api/metrics           # Prometheus gauges for monitoring
```

Restart policy is `unless-stopped`: containers come back after crashes and reboots (enable Docker at boot:
`sudo systemctl enable docker`).

## 3. Backups and monitoring

```bash
# daily database backup at 03:17, keep 14 days
( crontab -l 2>/dev/null; echo '17 3 * * * cd ~/promovent-src/promovent && scripts/db.sh backup /var/backups/promovent && find /var/backups/promovent -name "*.dump" -mtime +14 -delete' ) | crontab -
```

Point Prometheus/Grafana (or any uptime checker) at `/api/metrics` and `/api/health`. Alert on `promovent_db_ok 0`,
`promovent_redis_ok 0`, `promovent_workers 0`, `promovent_guardian_locked 1`.

## 4. Paper first, then assisted live

1. Leave `PROMOVENT_MODE=paper` for weeks. The autopilot trades only strategy/pair/timeframe combinations that passed
   validation on live data; until one does, it waits.
2. Testnet: create keys at testnet.binance.vision (HMAC), set `PROMOVENT_BINANCE_API_KEY/SECRET`,
   `PROMOVENT_EXCHANGE_TESTNET=yes`, `PROMOVENT_MODE=assisted_live`, `PROMOVENT_ENABLE_LIVE=yes`; `docker compose up -d`.
   `/trading` → Live preflight must show every check PASS; Propose → Confirm places one testnet order with its OCO stop.
3. Real money only after that, with a **new** key: Spot trading ON, Withdrawals OFF, Margin/Futures OFF,
   IP whitelist = the VPS IP. Promovent refuses keys that allow withdrawals. Set `PROMOVENT_EXCHANGE_TESTNET=no`.
   Every order still needs your confirmation in assisted mode. Autonomous mode additionally needs an admin activation
   with allow-lists and a per-order cap.

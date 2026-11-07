-- Promovent schema v1 (SQLite). Postgres/TimescaleDB are not wired yet (see STATUS.md).
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_orders (
  client_order_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL, symbol TEXT NOT NULL, side INTEGER NOT NULL, qty REAL NOT NULL,
  price REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL, strategy TEXT NOT NULL,
  status TEXT NOT NULL, decision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_order_id TEXT NOT NULL REFERENCES paper_orders(client_order_id),
  symbol TEXT NOT NULL, side INTEGER NOT NULL, qty REAL NOT NULL, entry REAL NOT NULL,
  exit REAL NOT NULL, reason TEXT NOT NULL, pnl REAL NOT NULL, fees REAL NOT NULL,
  opened_at TEXT NOT NULL, closed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT, message TEXT NOT NULL, delivered TEXT NOT NULL DEFAULT 'dashboard'
);

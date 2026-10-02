CREATE TABLE IF NOT EXISTS visitors (
  day TEXT NOT NULL,
  ip_key TEXT NOT NULL,
  ip_address TEXT NOT NULL,
  bonus INTEGER NOT NULL CHECK (bonus >= 0 AND bonus <= 99),
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  PRIMARY KEY (day, ip_key)
);

CREATE TABLE IF NOT EXISTS dwell (
  day TEXT NOT NULL,
  ip_key TEXT NOT NULL,
  category TEXT NOT NULL,
  seconds INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (day, ip_key, category)
);

CREATE TABLE IF NOT EXISTS sessions (
  day TEXT NOT NULL,
  ip_key TEXT NOT NULL,
  session_id TEXT NOT NULL,
  category TEXT NOT NULL,
  last_seen INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (day, ip_key, session_id)
);

CREATE INDEX IF NOT EXISTS idx_visitors_day_first_seen
  ON visitors(day, first_seen);

CREATE INDEX IF NOT EXISTS idx_dwell_day_ip
  ON dwell(day, ip_key);

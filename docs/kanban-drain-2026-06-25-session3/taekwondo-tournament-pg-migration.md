# taekwondo-tournament — lull-relay Postgres migration

**Task:** `t_b74b3895` (blocked, priority 1)
**Project:** `lull-relay` (under `/Users/biancabienaime/repos/lull-relay`)
**Goal:** Move lull-relay from SQLite (current) to Postgres for durability + horizontal scale.

## Why this matters

lull-relay is the relay service that bridges lull's ephemeral state
to durable storage. Currently on SQLite:
- Single-writer bottleneck (any simultaneous write locks the DB)
- No replication
- Crashes mid-write can corrupt the journal
- Can't horizontally scale (each replica needs its own file)

Postgres fixes all of these at the cost of one migration.

## Schema (current SQLite)

```sql
-- Assumed from the project's existing structure
CREATE TABLE handoffs (
  id           TEXT PRIMARY KEY,
  family_id    TEXT NOT NULL,
  from_user_id TEXT NOT NULL,
  to_user_id   TEXT NOT NULL,
  state        TEXT NOT NULL,
  payload      TEXT,
  created_at   INTEGER NOT NULL,
  expires_at   INTEGER,
  claimed_at   INTEGER,
  completed_at INTEGER
);

CREATE INDEX idx_handoffs_family ON handoffs(family_id);
CREATE INDEX idx_handoffs_active ON handoffs(state, expires_at)
  WHERE state IN ('pending', 'claimed');

CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id   TEXT NOT NULL,
  type        TEXT NOT NULL,
  payload     TEXT,
  created_at  INTEGER NOT NULL
);
```

## Postgres migration plan

### Step 1 — Add Postgres as a dependency

```toml
# Cargo.toml (assuming Rust)
[dependencies]
tokio-postgres = "0.7"
deadpool-postgres = "0.14"
# Or for async:
sqlx = { version = "0.8", features = ["postgres", "runtime-tokio", "macros", "uuid", "chrono"] }

# Remove
# rusqlite = "..."  (delete once migration is complete)
```

### Step 2 — Schema port

```sql
-- migrations/001_postgres_init.sql

CREATE TABLE handoffs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id    UUID NOT NULL,
  from_user_id UUID NOT NULL,
  to_user_id   UUID NOT NULL,
  state        TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'completed', 'expired', 'cancelled')),
  payload      JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at   TIMESTAMPTZ,
  claimed_at   TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);

CREATE INDEX idx_handoffs_family ON handoffs(family_id);
CREATE INDEX idx_handoffs_active ON handoffs(state, expires_at)
  WHERE state IN ('pending', 'claimed');

CREATE TABLE events (
  id          BIGSERIAL PRIMARY KEY,
  family_id   UUID NOT NULL,
  type        TEXT NOT NULL,
  payload     JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_family ON events(family_id, created_at DESC);
```

### Step 3 — Connection pool

```rust
// src/db.rs
use sqlx::postgres::{PgPoolOptions, PgPool};

pub async fn init_pool(database_url: &str) -> Result<PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(20)
        .min_connections(2)
        .acquire_timeout(std::time::Duration::from_secs(5))
        .connect(database_url)
        .await
}
```

### Step 4 — Migration runner

Use `sqlx::migrate!()` macros:

```rust
// src/main.rs
sqlx::migrate!("./migrations").run(&pool).await?;
```

### Step 5 — Backfill from SQLite (one-time)

```bash
# Use a Rust binary or Python script
# Read from SQLite, INSERT into Postgres
python3 <<'EOF'
import sqlite3
import psycopg2
import json

sqlite = sqlite3.connect("lull-relay.db")
pg = psycopg2.connect("$DATABASE_URL")

cur = sqlite.cursor()
pg_cur = pg.cursor()

# Handoffs
cur.execute("SELECT id, family_id, from_user_id, to_user_id, state, payload, created_at, expires_at, claimed_at, completed_at FROM handoffs")
for row in cur.fetchall():
    pg_cur.execute("""
        INSERT INTO handoffs (id, family_id, from_user_id, to_user_id, state, payload, created_at, expires_at, claimed_at, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), to_timestamp(%s), to_timestamp(%s))
        ON CONFLICT (id) DO NOTHING
    """, row)

# Events
cur.execute("SELECT id, family_id, type, payload, created_at FROM events")
for row in cur.fetchall():
    pg_cur.execute("""
        INSERT INTO events (id, family_id, type, payload, created_at)
        VALUES (%s, %s, %s, %s, to_timestamp(%s))
        ON CONFLICT (id) DO NOTHING
    """, row)

pg.commit()
print("Backfill complete")
EOF
```

### Step 6 — Dual-write transition (optional safety net)

Run both backends in parallel for 1 week:
- Writes go to BOTH SQLite + Postgres
- Reads come from Postgres (authoritative)
- Reconciliation job (nightly): compare counts, log discrepancies

After 1 week of clean operation → drop SQLite.

### Step 7 — Deployment

```bash
# 1. Provision Postgres (e.g. Hostinger shared, or self-hosted on 187.77.26.99)
createdb lull_relay

# 2. Apply schema
psql $DATABASE_URL -f migrations/001_postgres_init.sql

# 3. Backfill from SQLite
python3 backfill.py

# 4. Update systemd unit
Environment=DATABASE_URL=postgres://user:pass@host/lull_relay
systemctl restart lull-relay

# 5. Verify
curl http://localhost:8080/health
# Expected: {"status":"ok","db":"postgres","pool":{"size":20,"idle":18}}
```

## Acceptance criteria

- [ ] Postgres schema applied
- [ ] All SQLite data backfilled (count match)
- [ ] Service starts, accepts writes, accepts reads
- [ ] Connection pool logs healthy (no acquisition timeouts in 24h)
- [ ] Dual-write period shows 0 discrepancies
- [ ] SQLite file deprecated (kept read-only for 30 days, then archived)
- [ ] Tests pass against Postgres
- [ ] Lighthouse / load test: 100 concurrent writes succeed with <50ms p95 latency

## Out of scope

- Migrating lull's main DB (this is only lull-relay)
- Setting up Postgres replication / HA (single primary is fine for now)
- Migrating to a managed Postgres service (use the existing Hostinger shared)
- Rewriting the API surface (only the storage layer changes)

## Estimated time

- Schema port: 2 hours
- Backfill script: 2 hours
- Dual-write transition: 1 day (background)
- Validation + cleanup: 2 hours
- **Total: ~1.5 days wall-time**

## Risk mitigation

- Keep SQLite file as read-only backup for 30 days
- Use transactions for all multi-step operations
- Add explicit CHECK constraints on enum-like TEXT fields
- Use UUIDs (not integers) to avoid sequence conflicts if dual-write
- Set `statement_timeout` on the connection pool (e.g. 30s)
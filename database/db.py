"""
SQLite connection management and schema.

A new connection is opened per request (stored on ``flask.g``) and closed at
teardown. Foreign keys are enabled so deleting a test cascades to its
individual query attempts.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS tests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    domain            TEXT    NOT NULL,
    record_type       TEXT    NOT NULL CHECK (record_type IN ('A', 'AAAA')),
    resolvers         TEXT    NOT NULL,             -- JSON list of resolver keys
    attempts          INTEGER NOT NULL,             -- attempts per resolver
    timeout_s         REAL    NOT NULL,
    created_at        TEXT    NOT NULL,             -- ISO-8601 UTC
    duration_ms       REAL,
    total_queries     INTEGER NOT NULL,
    successful        INTEGER NOT NULL,
    no_data           INTEGER NOT NULL,
    failed            INTEGER NOT NULL,
    median_latency_ms REAL,                         -- successful attempts only
    failure_rate      REAL,                         -- failed / total x 100
    outcome           TEXT    NOT NULL,
    report_json       TEXT    NOT NULL              -- comparison + diagnosis snapshot
);

CREATE INDEX IF NOT EXISTS idx_tests_created ON tests(created_at);
CREATE INDEX IF NOT EXISTS idx_tests_domain  ON tests(domain);

CREATE TABLE IF NOT EXISTS query_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id       INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    resolver_key  TEXT    NOT NULL,
    resolver_name TEXT    NOT NULL,
    resolver_ip   TEXT    NOT NULL,
    attempt_no    INTEGER NOT NULL,
    domain        TEXT    NOT NULL,
    record_type   TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    rcode         TEXT,
    success       INTEGER NOT NULL,
    latency_ms    REAL,
    records       TEXT    NOT NULL,                 -- JSON list
    cname_chain   TEXT    NOT NULL,                 -- JSON list
    ttl           INTEGER,
    transport     TEXT,
    tcp_fallback  INTEGER NOT NULL DEFAULT 0,
    flags         TEXT,
    timestamp     TEXT    NOT NULL,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_test     ON query_attempts(test_id);
CREATE INDEX IF NOT EXISTS idx_attempts_resolver ON query_attempts(resolver_key, timestamp);
"""


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=0, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: str) -> None:
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def connect_standalone(path: str) -> sqlite3.Connection:
    """Connection for use outside a request (background test jobs)."""
    return _connect(path)


def init_app(app) -> None:
    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)

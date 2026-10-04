"""SQLite database access helpers for RxSpark."""
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import current_app, g


def now_str() -> str:
    """Local timestamp string used across all tables."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist yet."""
    db_path = Path(current_app.config["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    db = sqlite3.connect(str(db_path))
    try:
        db.executescript(schema)
        db.commit()
    finally:
        db.close()


def next_sequence(db: sqlite3.Connection, name: str) -> int:
    """Atomically increment and return a named counter (unique numbering)."""
    db.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
    row = db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
    if row is None:
        db.execute("INSERT INTO counters (name, value) VALUES (?, 1)", (name,))
        return 1
    return int(row["value"])


def next_patient_code(db: sqlite3.Connection) -> str:
    return f"PT-{next_sequence(db, 'patient_code'):05d}"


def next_prescription_number(db: sqlite3.Connection) -> str:
    return f"RX-{next_sequence(db, 'prescription_number'):06d}"

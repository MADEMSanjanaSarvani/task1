"""Postgres/Supabase connection helper shared by every pipeline script."""
import decimal
import os
import psycopg2
import psycopg2.extras


def json_default(obj):
    """json.dumps(default=...) helper for values Postgres hands back that the
    stdlib json module doesn't natively support - NUMERIC columns come back
    as Decimal via RealDictCursor, which isn't JSON-serializable on its own."""
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def get_connection():
    """Connect using SUPABASE_DB_URL (a standard Postgres connection string)."""
    dsn = os.environ["SUPABASE_DB_URL"]
    return psycopg2.connect(dsn)


def insert_rows(conn, table, rows):
    """Insert a list of dicts into `table`, one row per dict. Returns inserted ids."""
    if not rows:
        return []
    columns = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING id"
    ids = []
    with conn.cursor() as cur:
        for row in rows:
            values = [row[c] for c in columns]
            cur.execute(sql, values)
            ids.append(cur.fetchone()[0])
    conn.commit()
    return ids


def select_rows(conn, sql, params=None):
    """Run a SELECT and return a list of dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def execute(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
    conn.commit()

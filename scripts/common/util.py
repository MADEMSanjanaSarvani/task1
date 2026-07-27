"""Small shared helpers: run_id generation and a standard top-level error-handling wrapper."""
import functools
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def new_run_id() -> str:
    return time.strftime("%Y%m%d") + "-" + str(int(time.time() * 1000))


def today() -> str:
    return time.strftime("%Y-%m-%d")


def run_main(workflow_name: str):
    """Decorator for each script's main(): logs to failed_runs + Discord/email on
    any uncaught exception, then exits non-zero so the GitHub Actions job shows
    red (which itself is a second, independent failure signal on top of the
    Discord alert)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from . import db, notify
            conn = None
            try:
                conn = db.get_connection()
                return fn(conn, *args, **kwargs)
            except Exception as e:  # noqa: BLE001 - top-level catch-all is the point
                logging.getLogger(workflow_name).exception("Run failed")
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    notify.log_failure(conn, workflow_name, e)
                else:
                    notify.notify_discord(f"🔴 Workflow **{workflow_name}** failed before DB connection: {e}")
                sys.exit(1)
            finally:
                if conn is not None:
                    conn.close()
        return wrapper
    return decorator

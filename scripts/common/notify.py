"""Discord + email alert helpers, and the shared failed_runs logger."""
import json
import logging
import os
import smtplib
import traceback
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def notify_discord(message: str, webhook_url: str | None = None):
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        requests.post(url, json={"content": message[:1900]}, timeout=10)
    except requests.RequestException as e:
        log.warning("Discord notify failed: %s", e)


def notify_email(subject: str, body: str):
    host = os.environ.get("SMTP_HOST")
    if not host:
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("ALERT_EMAIL", ""))
        msg["To"] = os.environ.get("ALERT_EMAIL", "")
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587))) as server:
            server.starttls()
            server.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
    except Exception as e:  # noqa: BLE001 - alerting must never crash the caller
        log.warning("Email notify failed: %s", e)


def log_failure(conn, workflow_name: str, exc: Exception, context: dict | None = None):
    """Mirrors the n8n Error Handler workflow: log to failed_runs, then alert."""
    error_message = str(exc)
    payload = json.dumps({"traceback": traceback.format_exc(), "context": context or {}})[:8000]
    try:
        from . import db
        db.execute(
            conn,
            "INSERT INTO failed_runs (workflow_name, failed_node, error_message, payload) VALUES (%s, %s, %s, %s)",
            (workflow_name, context.get("step") if context else None, error_message, payload),
        )
    except Exception as e:  # noqa: BLE001
        log.error("Could not write to failed_runs: %s", e)

    notify_discord(f"🔴 Workflow **{workflow_name}** failed: ```{error_message[:1500]}```")
    notify_email(f"[AI Content Automation] Failure: {workflow_name}", f"{error_message}\n\n{payload}")

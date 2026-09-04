"""Google Sheets / Airtable / Notion sync helpers for the daily report step.

Every function here is best-effort: it logs and returns on failure rather than
raising, mirroring the n8n version's continueOnFail on every secondary-storage
sync node - Postgres remains the system of record regardless of whether these
succeed.
"""
import logging
import os

import requests

log = logging.getLogger(__name__)


def sync_google_sheets(rows: list[dict], sheet_name: str):
    """Appends rows to a tab via a Google Service Account (gspread). Requires
    GOOGLE_SERVICE_ACCOUNT_JSON (the service account key file contents) and
    GOOGLE_SHEETS_SPREADSHEET_ID, and that the sheet has been shared with the
    service account's client_email."""
    if not rows:
        return
    try:
        import json as _json
        import gspread
        from google.oauth2.service_account import Credentials

        creds_info = _json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
        creds = Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"])
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=len(rows[0]))
            ws.append_row(list(rows[0].keys()))
        for row in rows:
            ws.append_row([_stringify(v) for v in row.values()])
    except Exception as e:  # noqa: BLE001
        log.warning("Google Sheets sync to %s failed: %s", sheet_name, e)


def sync_airtable(rows: list[dict], table_name: str):
    if not rows:
        return
    base_id = os.environ.get("AIRTABLE_BASE_ID")
    api_key = os.environ.get("AIRTABLE_API_KEY")
    if not base_id or not api_key:
        return
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for row in rows:
        try:
            requests.post(
                url, headers=headers,
                json={"fields": {k: _stringify(v) for k, v in row.items()}},
                timeout=15,
            )
        except requests.RequestException as e:
            log.warning("Airtable sync to %s failed: %s", table_name, e)


def sync_notion(title: str, database_id_env: str):
    """Creates a title-only page in the given Notion database. Add more
    properties in propertiesUi below to match your database's actual schema."""
    database_id = os.environ.get(database_id_env)
    token = os.environ.get("NOTION_TOKEN")
    if not database_id or not token:
        return
    try:
        requests.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": database_id},
                "properties": {"Name": {"title": [{"text": {"content": title[:200]}}]}},
            },
            timeout=15,
        )
    except requests.RequestException as e:
        log.warning("Notion sync failed for %s: %s", database_id_env, e)


def _stringify(value):
    import decimal
    import json
    # NUMERIC columns come back from Postgres as Decimal, which neither
    # gspread nor requests' json= encoding can serialize on its own - convert
    # up front so a raw score/price column never crashes a "best-effort" sync.
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=lambda v: float(v) if isinstance(v, decimal.Decimal) else str(v))
    return value

"""Fuentes de correo: simulada (JSON local) o Gmail real (OAuth, solo lectura)."""
import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..config import Settings
from ..schemas import EmailIn

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def load_simulated(settings: Settings) -> list[EmailIn]:
    data = json.loads(settings.sample_emails_file.read_text(encoding="utf-8"))
    return [EmailIn(**item) for item in data]


def load_gmail(settings: Settings, max_results: int = 25) -> list[EmailIn]:  # pragma: no cover - requiere OAuth
    """Lee correos de Gmail. Primera ejecución: abre el navegador para autorizar (solo lectura)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if settings.gmail_token_file.exists():
        creds = Credentials.from_authorized_user_file(str(settings.gmail_token_file), GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_file), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        settings.gmail_token_file.write_text(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    listing = service.users().messages().list(userId="me", q=settings.gmail_query, maxResults=max_results).execute()

    emails = []
    for ref in listing.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        try:
            received = parsedate_to_datetime(headers.get("date", ""))
        except (TypeError, ValueError):
            received = datetime.now(timezone.utc)
        emails.append(
            EmailIn(
                message_id=msg["id"],
                sender=headers.get("from", ""),
                subject=headers.get("subject", ""),
                body=_plain_body(msg["payload"]) or msg.get("snippet", ""),
                received_at=received,
            )
        )
    return emails


def _plain_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _plain_body(part)
        if text:
            return text
    return ""


def fetch_emails(settings: Settings) -> list[EmailIn]:
    return load_gmail(settings) if settings.email_mode == "gmail" else load_simulated(settings)

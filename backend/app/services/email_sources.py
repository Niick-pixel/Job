"""Fuentes de correo: simulada (JSON local) o Gmail real (OAuth).

Permisos de Gmail: leer (para clasificar respuestas) y crear borradores (para dejarte los seguimientos
dentro del hilo de la empresa). La app nunca envía correos: los borradores los envías tú desde Gmail.
"""
import base64
import json
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

from ..config import Settings
from ..schemas import EmailIn

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]


def load_simulated(settings: Settings) -> list[EmailIn]:
    data = json.loads(settings.sample_emails_file.read_text(encoding="utf-8"))
    return [EmailIn(**item) for item in data]


READ_SCOPE, COMPOSE_SCOPE = GMAIL_SCOPES


class GmailAuthNeeded(RuntimeError):
    """Falta un permiso de Gmail y no se puede pedir ahora (p. ej. el agente en segundo plano)."""


def gmail_service(settings: Settings, *, compose: bool = False, interactive: bool = True):  # pragma: no cover - OAuth
    """Cliente de Gmail. Para leer basta el permiso de lectura (los tokens de versiones anteriores siguen
    valiendo); para crear borradores hace falta además el de redacción, que se pide al primer uso.
    Con interactive=False nunca abre el navegador: lanza GmailAuthNeeded."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    needed = GMAIL_SCOPES if compose else [READ_SCOPE]
    creds = None
    if settings.gmail_token_file.exists():
        creds = Credentials.from_authorized_user_file(str(settings.gmail_token_file))
        if not creds.has_scopes(needed):
            creds = None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        settings.gmail_token_file.write_text(creds.to_json())
    if not creds or not creds.valid:
        if not interactive:
            raise GmailAuthNeeded("Autoriza Gmail desde la app (Correos → Sincronizar)")
        flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_file), GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        settings.gmail_token_file.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def load_gmail(settings: Settings, max_results: int = 25, service=None, interactive: bool = True) -> list[EmailIn]:
    """Lee correos de Gmail. Primera ejecución: abre el navegador para autorizar."""
    service = service or gmail_service(settings, interactive=interactive)
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
                thread_id=msg.get("threadId"),
                rfc_message_id=headers.get("message-id"),
            )
        )
    return emails


def build_draft(to: str, subject: str, body: str, *, thread_id: str | None = None, in_reply_to: str | None = None,
                reply_subject: str | None = None) -> dict:
    """Cuerpo para users.drafts.create. Si hay hilo, va como respuesta (Gmail lo agrupa en la conversación)."""
    msg = EmailMessage()
    msg["To"] = to
    if thread_id and reply_subject:
        subject = reply_subject if reply_subject.lower().startswith(("re:", "re :")) else f"Re: {reply_subject}"
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    payload = {"message": {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}}
    if thread_id:
        payload["message"]["threadId"] = thread_id
    return payload


def create_draft(settings: Settings, to: str, subject: str, body: str, *, thread_id: str | None = None,
                 in_reply_to: str | None = None, reply_subject: str | None = None, service=None) -> dict:
    service = service or gmail_service(settings, compose=True)
    draft = service.users().drafts().create(userId="me", body=build_draft(
        to, subject, body, thread_id=thread_id, in_reply_to=in_reply_to, reply_subject=reply_subject)).execute()
    message_id = (draft.get("message") or {}).get("id")
    return {"draft_id": draft.get("id"), "thread_id": thread_id,
            "url": f"https://mail.google.com/mail/u/0/#drafts?compose={message_id}" if message_id else
                   "https://mail.google.com/mail/u/0/#drafts"}


def same_address(a: str, b: str) -> bool:
    return parseaddr(a)[1].lower() == parseaddr(b)[1].lower() != ""


def _plain_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _plain_body(part)
        if text:
            return text
    return ""


def fetch_emails(settings: Settings, interactive: bool = True) -> list[EmailIn]:
    return load_gmail(settings, interactive=interactive) if settings.email_mode == "gmail" else load_simulated(settings)

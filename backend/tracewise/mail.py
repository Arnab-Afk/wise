"""Transactional email over SMTP (STARTTLS on 587, implicit TLS on 465).

Every message is rendered and written to email_log first, then sent on a background thread, so a
slow mail server never holds up a request. Without SMTP settings, messages are logged as
'skipped' and can still be previewed in the console.
"""

import logging
import os
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from . import db

log = logging.getLogger("tracewise.mail")
HOST = os.environ.get("SMTP_HOST", "")
PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
USERNAME = os.environ.get("SMTP_USERNAME", "")
PASSWORD = os.environ.get("SMTP_PASSWORD", "")
FROM = os.environ.get("SMTP_FROM", "")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")


def enabled() -> bool:
    return bool(HOST and FROM)


def _deliver(email_id: int, to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    name, addr = parseaddr(FROM)
    msg["From"] = formataddr((name or "Tracewise", addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] if "@" in addr else None)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        context = ssl.create_default_context()
        if PORT == 465:
            server = smtplib.SMTP_SSL(HOST, PORT, timeout=20, context=context)
        else:
            server = smtplib.SMTP(HOST, PORT, timeout=20)
            server.starttls(context=context)
        with server:
            if USERNAME:
                server.login(USERNAME, PASSWORD)
            server.send_message(msg)
        db.query("UPDATE email_log SET status = 'sent', sent_at = now() WHERE id = %s", email_id)
    except Exception as exc:
        log.warning("email %s to %s failed: %s", email_id, to, exc)
        db.query("UPDATE email_log SET status = 'failed', error = %s WHERE id = %s", str(exc)[:500], email_id)


def send(to: str, template: str, message: dict) -> int:
    """Log a rendered message ({subject, text, html}) and send it in the background."""
    row = db.one(
        "INSERT INTO email_log (to_email, template, subject, text_body, html_body, status)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        to, template, message["subject"], message["text"], message["html"],
        "queued" if enabled() else "skipped")
    if enabled():
        _pool.submit(_deliver, row["id"], to, message["subject"], message["text"], message["html"])
    else:
        log.info("SMTP not configured; email %s (%s) to %s logged only", row["id"], template, to)
    return row["id"]

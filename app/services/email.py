import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

from app.config import settings


def _send_gmail_sync(to: list[str], subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_user
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(settings.gmail_user, settings.gmail_app_password)
        server.send_message(msg)


async def send_gmail(to: list[str], subject: str, body: str) -> None:
    await asyncio.to_thread(_send_gmail_sync, to, subject, body)

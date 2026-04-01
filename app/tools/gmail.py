"""Gmail send tool — send emails via Gmail SMTP using app credentials."""

import argparse
import asyncio
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def _send_sync(to: list[str], subject: str, body: str) -> None:
    from app.config import settings

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
    await asyncio.to_thread(_send_sync, to, subject, body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an email via Gmail SMTP.")
    parser.add_argument("--to", required=True, nargs="+", metavar="ADDRESS",
                        help="One or more recipient addresses")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", help="Email body text")
    parser.add_argument("--body-file", metavar="FILE",
                        help="Path to a file whose contents will be used as the body")
    args = parser.parse_args()

    if args.body_file:
        body = Path(args.body_file).read_text()
    elif args.body:
        body = args.body
    else:
        print("Reading body from stdin (Ctrl-D to finish):", file=sys.stderr)
        body = sys.stdin.read()

    asyncio.run(send_gmail(to=args.to, subject=args.subject, body=body))
    print(f"Email sent to {', '.join(args.to)}")


if __name__ == "__main__":
    main()

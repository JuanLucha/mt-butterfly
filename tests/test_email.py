import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_send_gmail_calls_smtp():
    mock_server = MagicMock()
    mock_smtp_cls = MagicMock(return_value=__import__("contextlib").nullcontext(mock_server))

    with patch("smtplib.SMTP_SSL") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__  = MagicMock(return_value=False)

        from app.services.email import send_gmail
        await send_gmail(["dest@example.com"], "Test subject", "Test body")

        mock_smtp.assert_called_once_with("smtp.gmail.com", 465, context=__import__("unittest.mock", fromlist=["ANY"]).ANY)
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_gmail_uses_correct_credentials():
    from app.config import settings
    settings.gmail_user = "test@gmail.com"
    settings.gmail_app_password = "app-pass-123"

    mock_server = MagicMock()
    with patch("smtplib.SMTP_SSL") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__  = MagicMock(return_value=False)

        from app.services.email import send_gmail
        await send_gmail(["a@b.com"], "subj", "body")

        mock_server.login.assert_called_once_with("test@gmail.com", "app-pass-123")


@pytest.mark.asyncio
async def test_send_gmail_multiple_recipients():
    mock_server = MagicMock()
    captured = {}

    def capture_send(msg):
        captured["to"] = msg["To"]

    mock_server.send_message.side_effect = capture_send

    with patch("smtplib.SMTP_SSL") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__  = MagicMock(return_value=False)

        from app.services.email import send_gmail
        await send_gmail(["a@x.com", "b@x.com"], "hi", "body")

        assert "a@x.com" in captured["to"]
        assert "b@x.com" in captured["to"]


@pytest.mark.asyncio
async def test_send_gmail_subject_and_body():
    mock_server = MagicMock()
    captured = {}

    def capture_send(msg):
        captured["subject"] = msg["Subject"]
        from email import message_from_string
        captured["body"] = msg.get_payload(0).get_payload()

    mock_server.send_message.side_effect = capture_send

    with patch("smtplib.SMTP_SSL") as mock_smtp:
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__  = MagicMock(return_value=False)

        from app.services.email import send_gmail
        await send_gmail(["x@y.com"], "My Subject", "My Body Text")

        assert captured["subject"] == "My Subject"
        assert "My Body Text" in captured["body"]

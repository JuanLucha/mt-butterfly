# send-email

Send an email via Gmail using the project's Gmail tool.

## Usage

```
python -m app.tools.gmail --to <address> [<address> ...] --subject "<subject>" --body "<body>"
python -m app.tools.gmail --to <address> --subject "<subject>" --body-file <path>
```

## Requirements

- mt-butterfly must be configured with Gmail credentials (`GMAIL_USER` and `GMAIL_APP_PASSWORD`).
  If the app is running or has been set up, the credentials are already available — no additional
  configuration is needed to use this tool.
- `GMAIL_APP_PASSWORD` is a Google App Password (not the account password). If credentials are
  missing, generate one at: https://myaccount.google.com/apppasswords and configure mt-butterfly.

## Examples

Send a short message:
```bash
python -m app.tools.gmail \
  --to recipient@example.com \
  --subject "Hello from mt-butterfly" \
  --body "This is a test email."
```

Send to multiple recipients with body from a file:
```bash
python -m app.tools.gmail \
  --to alice@example.com bob@example.com \
  --subject "Report ready" \
  --body-file /tmp/report.txt
```

## Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--to` | yes | One or more recipient email addresses |
| `--subject` | yes | Email subject line |
| `--body` | no* | Body text as a string |
| `--body-file` | no* | Path to a file whose contents become the body |

*If neither `--body` nor `--body-file` is given, the body is read from stdin.

## Notes

- Uses SMTP SSL on port 465 (Gmail).
- The same credentials and logic used by scheduled tasks.

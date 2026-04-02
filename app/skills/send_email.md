# send-email

Send an email via Gmail using the project's Gmail CLI tool.

## Usage

```
mt-butterfly-gmail --to <address> [<address> ...] --subject "<subject>" --body "<body>"
mt-butterfly-gmail --to <address> --subject "<subject>" --body-file <path>
mt-butterfly-gmail --to <address> --subject "<subject>" --body-file <path.html> --html
```

Use `--html` when the body is an HTML file so it renders correctly in email clients.

## IMPORTANT: Credentials are automatic

Gmail credentials (`GMAIL_USER` and `GMAIL_APP_PASSWORD`) are **already configured in the environment**. Do NOT:
- Set environment variables manually (e.g. `export GMAIL_USER=...`)
- Read, search for, or print credentials from `.env` files or `printenv`
- Pass credentials as command arguments

Just call `mt-butterfly-gmail` directly — it will pick up the credentials automatically.

## Examples

Send a short message:
```bash
mt-butterfly-gmail \
  --to recipient@example.com \
  --subject "Hello from mt-butterfly" \
  --body "This is a test email."
```

Send to multiple recipients with body from a file:
```bash
mt-butterfly-gmail \
  --to alice@example.com bob@example.com \
  --subject "Report ready" \
  --body-file /tmp/report.txt
```

Send an HTML email:
```bash
mt-butterfly-gmail \
  --to recipient@example.com \
  --subject "Weekly digest" \
  --body-file /tmp/digest.html \
  --html
```

## Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--to` | yes | One or more recipient email addresses |
| `--subject` | yes | Email subject line |
| `--body` | no* | Body text as a string |
| `--body-file` | no* | Path to a file whose contents become the body |
| `--html` | no | Treat body as HTML (use with `--body-file` for HTML files) |

*If neither `--body` nor `--body-file` is given, the body is read from stdin.

## Notes

- Uses SMTP SSL on port 465 (Gmail).
- The same credentials and logic used by scheduled tasks.

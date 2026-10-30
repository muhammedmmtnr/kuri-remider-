# Kuri Payment Reminder

A small, menu-driven Python application for sending individual Kuri payment
reminders through Gmail SMTP. It uses Gmail's encrypted STARTTLS connection,
validates and deduplicates contacts, and keeps a local report of attempted
messages.

## Requirements

- Windows 10 or later with PowerShell
- Python 3.10 or later
- A Gmail account with 2-Step Verification enabled and a Google App Password

Only `python-dotenv` is required; SMTP, CSV handling, HTML email creation, and
report output use Python's standard library.

## Install

Open PowerShell and run:

```powershell
cd C:\Users\msaje\kuri-reminder
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

If PowerShell prevents activation, allow it for this PowerShell window only,
then activate the environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Configure Gmail

Create `.env` from the example only if you do not already have a `.env` file:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set the values in `.env`:

```dotenv
SMTP_USER=growup710@gmail.com
SMTP_APP_PASSWORD=your_16_character_google_app_password
SENDER_NAME=Kuri Management
SEND_DELAY_SECONDS=3
```

Create an App Password from your Google Account's Security settings after
enabling 2-Step Verification. Use that App Password, not your normal Gmail
password. Google may display the App Password in groups separated by spaces;
the application removes those spaces before authenticating. Never share `.env`
or add it to Git.

`SEND_DELAY_SECONDS` is the pause between messages. Set it to a number greater
than or equal to zero; the default is 3 seconds. Gmail imposes account sending
limits. The application stops when it detects an authentication or quota
error, but you should still send only to recipients who expect these reminders.

## Prepare the contacts

Keep the original `emails.csv` in the project directory. It must have these
column names:

```csv
email,first_name
customer1@gmail.com,Customer One
customer2@gmail.com,Customer Two
```

The loader preserves names, skips blank or malformed addresses, and removes
duplicate email addresses without changing the CSV file. Only valid, unique
contacts are included in the count displayed before sending.

## Run the application

From the project directory, start the terminal menu:

```powershell
py .\bulk_email.py
```

Menu options:

1. Test the Gmail SMTP connection and authentication without sending a message.
2. Send a test message to the configured `SMTP_USER` address.
3. Preview the plain-text reminder and its sender/subject.
4. Send one personalized message per valid contact.
5. View the valid, unique contact count.
6. View the sending report.
7. Exit.

Bulk sending never starts automatically. Before option 4 sends, it displays
the number of valid recipients and asks you to type exactly `SEND`. Any other
response cancels the operation. Each email has one recipient in its `To`
header, so recipients cannot see one another's addresses. The message includes
both a plain-text alternative and a responsive HTML version.

## Sending report

The application appends results to `send_report.csv` after a send operation.
It records the recipient, first name, local date/time with timezone, `SENT` or
`FAILED` status, and an error message when applicable. `SENT` means Gmail
accepted the message; it does not guarantee delivery to the recipient's inbox.
SMTP credentials are never written to the report. The report may contain
personal contact information, so keep it private.

## Run tests

The tests use a mocked SMTP client and never contact Gmail or send real mail:

```powershell
py -m unittest discover -s tests -v
```

## Files and privacy

- `.env` stores private SMTP settings and is ignored by Git.
- `emails.csv` contains private contact data and is ignored by Git.
- `send_report.csv` contains recipient results and is ignored by Git.
- `.env.example` contains placeholders only and can be version controlled.
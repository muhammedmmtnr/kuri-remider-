import csv
import html
import os
import re
import smtplib
import socket
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
CONTACTS_FILE = PROJECT_DIR / "emails.csv"
REPORT_FILE = PROJECT_DIR / "send_report.csv"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT_SECONDS = 30
SUBJECT = "Kuri Payment Reminder"
REPORT_FIELDS = (
    "recipient_email",
    "first_name",
    "sent_at",
    "status",
    "error_message",
)

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


class ConfigurationError(Exception):
    """Raised when the required local Gmail settings are unavailable."""


class ContactFileError(Exception):
    """Raised when the contacts CSV cannot be read or is not formatted."""


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Settings:
    smtp_user: str
    app_password: str
    sender_name: str
    delay_seconds: float


@dataclass
class SendResult:
    recipient_email: str
    first_name: str
    status: str
    error_message: str = ""
    sent_at: str = field(default_factory=current_timestamp)


def load_settings(env_file: Path = ENV_FILE) -> Settings:
    if not env_file.is_file():
        raise ConfigurationError(
            f".env was not found at {env_file}. Copy .env.example to .env "
            "and add your Gmail App Password."
        )

    load_dotenv(dotenv_path=env_file, override=False)
    smtp_user = os.getenv("SMTP_USER", "").strip()
    app_password = os.getenv("SMTP_APP_PASSWORD", "").strip().replace(" ", "")
    sender_name = os.getenv("SENDER_NAME", "Kuri Management").strip()
    delay_value = os.getenv("SEND_DELAY_SECONDS", "3").strip()

    missing = [
        name
        for name, value in (
            ("SMTP_USER", smtp_user),
            ("SMTP_APP_PASSWORD", app_password),
            ("SENDER_NAME", sender_name),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "Missing required .env setting(s): " + ", ".join(missing)
        )

    try:
        delay_seconds = float(delay_value)
    except ValueError as error:
        raise ConfigurationError(
            "SEND_DELAY_SECONDS must be a number greater than or equal to 0."
        ) from error
    if delay_seconds < 0:
        raise ConfigurationError(
            "SEND_DELAY_SECONDS must be a number greater than or equal to 0."
        )

    if not is_valid_email(smtp_user):
        raise ConfigurationError("SMTP_USER must be a valid Gmail email address.")

    return Settings(smtp_user, app_password, sender_name, delay_seconds)


def is_valid_email(address: str) -> bool:
    address = address.strip()
    if not address or any(character.isspace() for character in address):
        return False
    if address.count("@") != 1 or not EMAIL_PATTERN.fullmatch(address):
        return False
    local_part = address.split("@", maxsplit=1)[0]
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        return False
    parsed_name, parsed_address = parseaddr(address)
    return not parsed_name and parsed_address == address


def load_contacts(csv_file: Path = CONTACTS_FILE) -> list[dict[str, str]]:
    if not csv_file.is_file():
        raise ContactFileError(
            f"Contact file was not found: {csv_file}. Create emails.csv "
            "with email and first_name columns."
        )

    try:
        with csv_file.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            headers = reader.fieldnames or []
            required_headers = {"email", "first_name"}
            missing_headers = required_headers.difference(headers)
            if missing_headers:
                raise ContactFileError(
                    "emails.csv is missing required column(s): "
                    + ", ".join(sorted(missing_headers))
                )

            contacts = []
            seen_emails = set()
            for row in reader:
                address = (row.get("email") or "").strip()
                if not is_valid_email(address):
                    continue
                normalized_address = address.casefold()
                if normalized_address in seen_emails:
                    continue
                seen_emails.add(normalized_address)
                contacts.append(
                    {
                        "email": address,
                        "first_name": (row.get("first_name") or "").strip(),
                    }
                )
            return contacts
    except (OSError, csv.Error) as error:
        raise ContactFileError(f"Could not read emails.csv: {error}") from error


def build_reminder(
    recipient_email: str,
    first_name: str,
    settings: Settings,
) -> EmailMessage:
    greeting_name = first_name.strip() or "there"
    greeting = f"Hello {greeting_name},"
    plain_text = (
        f"{greeting}\n\n"
        "This is a friendly reminder from Kuri regarding your pending payment.\n\n"
        "If you have already completed your payment, please ignore this reminder.\n\n"
        "If you need any clarification or assistance, please contact the Kuri "
        "management team.\n\n"
        "Thank you.\n\n"
        "Regards,\n"
        f"{settings.sender_name}\n"
    )
    safe_name = html.escape(greeting_name)
    safe_sender = html.escape(settings.sender_name)
    html_content = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(SUBJECT)}</title>
  </head>
  <body style="margin:0;padding:24px;background-color:#f4f6f8;font-family:Arial,Helvetica,sans-serif;color:#243042;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto;background-color:#ffffff;border-radius:12px;">
      <tr>
        <td style="padding:32px 28px;">
          <h1 style="margin:0 0 24px;color:#174a3a;font-size:24px;line-height:1.3;">Kuri Payment Reminder</h1>
          <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">{html.escape(greeting)}</p>
          <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">This is a friendly reminder from Kuri regarding your pending payment.</p>
          <p style="margin:0 0 16px;font-size:16px;line-height:1.6;">If you have already completed your payment, please ignore this reminder.</p>
          <p style="margin:0 0 24px;font-size:16px;line-height:1.6;">If you need any clarification or assistance, please contact the Kuri management team.</p>
          <p style="margin:0 0 20px;font-size:16px;line-height:1.6;">Thank you.</p>
          <p style="margin:0;font-size:16px;line-height:1.6;">Regards,<br>{safe_sender}</p>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    message = EmailMessage()
    message["From"] = formataddr((settings.sender_name, settings.smtp_user))
    message["To"] = recipient_email
    message["Subject"] = SUBJECT
    message.set_content(plain_text)
    message.add_alternative(html_content, subtype="html")
    return message


@contextmanager
def authenticated_smtp(
    settings: Settings,
    smtp_factory=None,
) -> Iterator[smtplib.SMTP]:
    factory = smtp_factory or smtplib.SMTP
    server = factory(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(settings.smtp_user, settings.app_password)
        yield server
    finally:
        server.close()


def is_quota_error(error: Exception) -> bool:
    if not isinstance(error, smtplib.SMTPResponseException):
        return False
    response = error.smtp_error
    response_text = (
        response.decode("utf-8", errors="replace")
        if isinstance(response, bytes)
        else str(response)
    ).casefold()
    quota_terms = ("quota", "sending limit", "rate limit", "too many messages")
    return error.smtp_code in (421, 450, 451, 452, 454) or any(
        term in response_text for term in quota_terms
    )


def smtp_error_message(error: Exception) -> str:
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "Gmail authentication failed. Check SMTP_USER and create/use a "
            "Google App Password (not your normal Gmail password)."
        )
    if is_quota_error(error):
        return (
            "Gmail reported a sending limit or quota error. Sending has stopped; "
            "wait before trying again."
        )
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "Gmail rejected the recipient address."
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "Network timeout while connecting to Gmail or sending the email."
    if isinstance(error, ssl.SSLError):
        return f"TLS negotiation with Gmail failed: {error}"
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return f"Gmail closed the SMTP connection unexpectedly: {error}"
    if isinstance(error, (smtplib.SMTPConnectError, ConnectionError, OSError)):
        return f"Could not connect to Gmail SMTP: {error}"
    if isinstance(error, smtplib.SMTPResponseException):
        response = error.smtp_error
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        return f"Gmail SMTP error {error.smtp_code}: {response}"
    if isinstance(error, smtplib.SMTPException):
        return f"SMTP error: {error}"
    return str(error)


def write_report(results: list[SendResult], report_file: Path = REPORT_FILE) -> None:
    if not results:
        return
    needs_header = not report_file.exists() or report_file.stat().st_size == 0
    with report_file.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_FIELDS)
        if needs_header:
            writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "recipient_email": result.recipient_email,
                    "first_name": result.first_name,
                    "sent_at": result.sent_at,
                    "status": result.status,
                    "error_message": result.error_message,
                }
            )


def send_reminders(
    contacts: list[dict[str, str]],
    settings: Settings,
    report_file: Path = REPORT_FILE,
    smtp_factory=None,
) -> list[SendResult]:
    results: list[SendResult] = []
    try:
        with authenticated_smtp(settings, smtp_factory=smtp_factory) as server:
            for index, person in enumerate(contacts):
                recipient = person["email"]
                first_name = person["first_name"]
                try:
                    refused = server.send_message(
                        build_reminder(recipient, first_name, settings)
                    )
                    if refused:
                        recipient_error = smtplib.SMTPRecipientsRefused(refused)
                        error_message = smtp_error_message(recipient_error)
                        results.append(
                            SendResult(recipient, first_name, "FAILED", error_message)
                        )
                        if is_quota_refusal(refused):
                            mark_remaining_failed(
                                results,
                                contacts[index + 1 :],
                                "Gmail reported a sending limit or quota error. "
                                "Sending has stopped; wait before trying again.",
                            )
                            break
                    else:
                        results.append(SendResult(recipient, first_name, "SENT"))
                except KeyboardInterrupt:
                    results.append(
                        SendResult(
                            recipient,
                            first_name,
                            "FAILED",
                            "Interrupted before delivery confirmation; delivery "
                            "status is unknown.",
                        )
                    )
                    mark_remaining_failed(
                        results,
                        contacts[index + 1 :],
                        "Not attempted: sending was interrupted.",
                    )
                    break
                except Exception as error:
                    error_message = smtp_error_message(error)
                    results.append(
                        SendResult(recipient, first_name, "FAILED", error_message)
                    )
                    if should_stop_sending(error):
                        mark_remaining_failed(
                            results, contacts[index + 1 :], error_message
                        )
                        break
                if index + 1 < len(contacts) and settings.delay_seconds:
                    try:
                        time.sleep(settings.delay_seconds)
                    except KeyboardInterrupt:
                        mark_remaining_failed(
                            results,
                            contacts[index + 1 :],
                            "Not attempted: sending was interrupted.",
                        )
                        break
    except Exception as error:
        error_message = smtp_error_message(error)
        results = [
            SendResult(
                person["email"], person["first_name"], "FAILED", error_message
            )
            for person in contacts
        ]
    write_report(results, report_file)
    return results


def is_quota_refusal(refused: dict) -> bool:
    for code, response in refused.values():
        response_text = (
            response.decode("utf-8", errors="replace")
            if isinstance(response, bytes)
            else str(response)
        ).casefold()
        if code in (421, 450, 451, 452, 454) or any(
            term in response_text
            for term in ("quota", "sending limit", "rate limit", "too many messages")
        ):
            return True
    return False


def should_stop_sending(error: Exception) -> bool:
    return isinstance(
        error,
        (
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
            socket.timeout,
            TimeoutError,
            ssl.SSLError,
            ConnectionError,
            OSError,
        ),
    ) or is_quota_error(error)


def mark_remaining_failed(
    results: list[SendResult],
    contacts: list[dict[str, str]],
    error_message: str,
) -> None:
    results.extend(
        SendResult(person["email"], person["first_name"], "FAILED", error_message)
        for person in contacts
    )


def send_test_email(settings: Settings) -> SendResult:
    contact = {"email": settings.smtp_user, "first_name": "there"}
    return send_reminders([contact], settings)[0]


def preview_email(settings: Settings) -> None:
    message = build_reminder(settings.smtp_user, "Customer", settings)
    print(f"\nFrom: {message['From']}")
    print(f"To: {message['To']}")
    print(f"Subject: {message['Subject']}\n")
    print(message.get_body(preferencelist=("plain",)).get_content())


def view_contact_count() -> None:
    try:
        contacts = load_contacts()
    except ContactFileError as error:
        print(f"ERROR: {error}")
        return
    print(f"Valid, unique contacts: {len(contacts)}")
    if not contacts:
        print("No valid contacts found. Check the email column in emails.csv.")


def show_report() -> None:
    if not REPORT_FILE.is_file():
        print("No sending report exists yet.")
        return
    try:
        with REPORT_FILE.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
    except (OSError, csv.Error) as error:
        print(f"ERROR: Could not read send_report.csv: {error}")
        return
    if not rows:
        print("The sending report is empty.")
        return
    for row in rows:
        print(
            f"{row.get('sent_at', '')} | {row.get('status', '')} | "
            f"{row.get('recipient_email', '')} | "
            f"{row.get('first_name', '')} | {row.get('error_message', '')}"
        )


def run_smtp_test() -> None:
    try:
        settings = load_settings()
        with authenticated_smtp(settings):
            print("SMTP connection and Gmail authentication succeeded.")
    except Exception as error:
        print(f"ERROR: {smtp_error_message(error)}")


def run_test_email() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as error:
        print(f"ERROR: {error}")
        return
    result = send_test_email(settings)
    print_result(result)
    print(f"Report updated: {REPORT_FILE.name}")


def run_preview() -> None:
    try:
        preview_email(load_settings())
    except ConfigurationError as error:
        print(f"ERROR: {error}")


def run_bulk_send() -> None:
    try:
        contacts = load_contacts()
    except ContactFileError as error:
        print(f"ERROR: {error}")
        return
    if not contacts:
        print("No valid contacts found. Nothing will be sent.")
        return

    print(f"\nValid, unique recipients: {len(contacts)}")
    try:
        settings = load_settings()
    except ConfigurationError as error:
        print(f"ERROR: {error}")
        return

    print(f"Sending delay: {settings.delay_seconds:g} seconds between emails.")
    confirmation = input(
        "This will send individual reminders to all listed recipients. "
        "Type SEND to confirm: "
    )
    if confirmation != "SEND":
        print("Cancelled. No reminders were sent.")
        return

    results = send_reminders(contacts, settings)
    for result in results:
        print_result(result)
    print(
        f"\nFinished. SENT: {sum(item.status == 'SENT' for item in results)}; "
        f"FAILED: {sum(item.status == 'FAILED' for item in results)}."
    )
    print(f"Report: {REPORT_FILE}")


def print_result(result: SendResult) -> None:
    if result.status == "SENT":
        print(f"SENT: {result.recipient_email}")
    else:
        print(f"FAILED: {result.recipient_email}: {result.error_message}")


def main() -> None:
    actions = {
        "1": ("Test SMTP connection", run_smtp_test),
        "2": ("Send test email to my own Gmail", run_test_email),
        "3": ("Preview reminder email", run_preview),
        "4": ("Send reminders to all valid contacts", run_bulk_send),
        "5": ("View contact count", view_contact_count),
        "6": ("View sending report", show_report),
    }
    while True:
        print(
            "\n=== Kuri Payment Reminder ===\n"
            "1. Test SMTP connection\n"
            "2. Send test email to my own Gmail\n"
            "3. Preview reminder email\n"
            "4. Send reminders to all valid contacts\n"
            "5. View contact count\n"
            "6. View sending report\n"
            "7. Exit"
        )
        choice = input("Choose an option (1-7): ").strip()
        if choice == "7":
            print("Goodbye.")
            return
        action = actions.get(choice)
        if action is None:
            print("Choose a number from 1 to 7.")
            continue
        try:
            action[1]()
        except KeyboardInterrupt:
            print("\nCancelled.")
        except OSError as error:
            print(f"ERROR: {error}")


if __name__ == "__main__":
    main()

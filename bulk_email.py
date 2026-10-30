
import csv
import os
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from dotenv import load_dotenv

# Load private Gmail credentials
load_dotenv()

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_APP_PASSWORD")
SENDER_NAME = os.getenv("SENDER_NAME", "Kuri Management")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# IMPORTANT:
# Start with test mode. This sends ONLY to your own test email.
SEND_MODE = "test"

TEST_EMAIL = SMTP_USER

SUBJECT = "Friendly Kuri Payment Reminder"

MESSAGE = """Dear {name},

This is a friendly reminder regarding your Kuri payment.

We kindly request you to complete your scheduled payment on time.

{amount_line}
{date_line}

If you have already made the payment, please ignore this reminder.

For any clarification, please contact us.

Thank you for your cooperation.

Regards,
{sender}
"""

def main():
    if not SMTP_USER or not SMTP_PASSWORD:
        print("ERROR: Gmail credentials missing in .env")
        return

    csv_file = Path("emails.csv")

    if not csv_file.exists():
        print("ERROR: emails.csv not found")
        return

    with csv_file.open(
        newline="", encoding="utf-8-sig"
    ) as file:
        contacts = list(csv.DictReader(file))

    if not contacts:
        print("No contacts found.")
        return

    print(f"Contacts loaded: {len(contacts)}")
    print(f"Mode: {SEND_MODE}")

    if SEND_MODE == "test":
        print(f"Test recipient: {TEST_EMAIL}")
    elif SEND_MODE != "all":
        print("Invalid SEND_MODE.")
        return

    if SEND_MODE == "all":
        confirm = input(
            "Send individual reminders to ALL contacts? Type YES: "
        )
        if confirm != "YES":
            print("Cancelled.")
            return

    sent = 0
    failed = 0

    try:
        with smtplib.SMTP(
            SMTP_SERVER, SMTP_PORT, timeout=30
        ) as server:

            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)

            targets = (
                [{"email": TEST_EMAIL, "first_name": "Test",
                  "amount": "", "due_date": ""}]
                if SEND_MODE == "test"
                else contacts
            )

            for person in targets:
                recipient = person.get("email", "").strip()
                name = person.get("first_name", "Member").strip()
                amount = person.get("amount", "").strip()
                due_date = person.get("due_date", "").strip()

                if not recipient:
                    failed += 1
                    continue

                amount_line = (
                    f"Kuri payment amount: {amount}"
                    if amount else ""
                )
                date_line = (
                    f"Payment due date: {due_date}"
                    if due_date else ""
                )

                email = EmailMessage()
                email["From"] = (
                    f"{SENDER_NAME} <{SMTP_USER}>"
                )
                email["To"] = recipient
                email["Subject"] = SUBJECT

                email.set_content(
                    MESSAGE.format(
                        name=name,
                        amount_line=amount_line,
                        date_line=date_line,
                        sender=SENDER_NAME
                    )
                )

                try:
                    server.send_message(email)
                    sent += 1
                    print(f"SUCCESS: {recipient}")

                except Exception as error:
                    failed += 1
                    print(f"FAILED: {recipient}: {error}")

                time.sleep(3)

    except Exception as error:
        print(f"SMTP ERROR: {error}")
        return

    # Save sending report
    with open(
        "sending_report.csv", "a",
        newline="", encoding="utf-8"
    ) as report:

        writer = csv.writer(report)

        if report.tell() == 0:
            writer.writerow(["Date", "Mode", "Sent", "Failed"])

        writer.writerow([
            datetime.now().isoformat(),
            SEND_MODE,
            sent,
            failed
        ])

    print("\n===== KURI REMINDER REPORT =====")
    print("Successfully sent:", sent)
    print("Failed:", failed)
    print("Report: sending_report.csv")


if __name__ == "__main__":
    main()

import csv
import os
import smtplib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bulk_email


def test_settings() -> bulk_email.Settings:
    return bulk_email.Settings(
        smtp_user="owner@gmail.com",
        app_password="test-app-password",
        sender_name="Kuri Management",
        delay_seconds=0,
    )


class ContactLoadingTests(unittest.TestCase):
    def write_contacts(self, directory: str, content: str) -> Path:
        csv_file = Path(directory) / "emails.csv"
        csv_file.write_text(content, encoding="utf-8")
        return csv_file

    def test_loads_valid_contacts_and_preserves_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_file = self.write_contacts(
                directory,
                "email,first_name\nmember@example.com,Sam Lee\n"
                "SECOND@example.com,Second Member\n",
            )

            contacts = bulk_email.load_contacts(csv_file)

        self.assertEqual(
            contacts,
            [
                {"email": "member@example.com", "first_name": "Sam Lee"},
                {"email": "SECOND@example.com", "first_name": "Second Member"},
            ],
        )

    def test_skips_invalid_empty_and_duplicate_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_file = self.write_contacts(
                directory,
                "email,first_name\n"
                "member@example.com,Member\n"
                "MEMBER@example.com,Duplicate\n"
                "invalid-address,Invalid\n"
                ",Empty\n",
            )

            contacts = bulk_email.load_contacts(csv_file)

        self.assertEqual(
            contacts, [{"email": "member@example.com", "first_name": "Member"}]
        )

    def test_rejects_csv_without_required_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_file = self.write_contacts(directory, "email,name\na@example.com,A\n")

            with self.assertRaisesRegex(bulk_email.ContactFileError, "first_name"):
                bulk_email.load_contacts(csv_file)

    def test_email_validation(self) -> None:
        self.assertTrue(bulk_email.is_valid_email("person.name+tag@example.com"))
        for address in (
            "",
            "missing-at",
            "person @example.com",
            "a..b@example.com",
            ".person@example.com",
            "person.@example.com",
        ):
            with self.subTest(address=address):
                self.assertFalse(bulk_email.is_valid_email(address))


class EmailGenerationTests(unittest.TestCase):
    def test_builds_personalized_multipart_email(self) -> None:
        message = bulk_email.build_reminder(
            "member@example.com", "Sam <Lee>", test_settings()
        )

        self.assertEqual(str(message["From"]), "Kuri Management <owner@gmail.com>")
        self.assertEqual(str(message["To"]), "member@example.com")
        self.assertEqual(str(message["Subject"]), "Kuri Payment Reminder")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        plain_text = message.get_body(preferencelist=("plain",)).get_content()
        html_text = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("Hello Sam <Lee>,", plain_text)
        self.assertIn("Hello Sam &lt;Lee&gt;,", html_text)
        self.assertIn("pending payment", plain_text)


class ConfigurationTests(unittest.TestCase):
    def test_missing_env_file_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                bulk_email.ConfigurationError, r"\.env was not found"
            ):
                bulk_email.load_settings(Path(directory) / ".env")

    def test_missing_configuration_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"SMTP_USER": "", "SMTP_APP_PASSWORD": "", "SENDER_NAME": ""},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    bulk_email.ConfigurationError, "SMTP_USER"
                ):
                    bulk_email.load_settings(env_file)


class SMTPTests(unittest.TestCase):
    def test_smtp_setup_uses_starttls_and_closes_connection(self) -> None:
        events = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                events.append(("connect", host, port, timeout))

            def ehlo(self):
                events.append("ehlo")

            def starttls(self, context):
                events.append(("starttls", context))

            def login(self, username, password):
                events.append(("login", username, password))

            def close(self):
                events.append("close")

        with bulk_email.authenticated_smtp(
            test_settings(), smtp_factory=FakeSMTP
        ):
            events.append("ready")

        self.assertEqual(events[0], ("connect", "smtp.gmail.com", 587, 30))
        self.assertEqual(events[1], "ehlo")
        self.assertEqual(events[2][0], "starttls")
        self.assertEqual(events[3], "ehlo")
        self.assertEqual(events[4], ("login", "owner@gmail.com", "test-app-password"))
        self.assertEqual(events[-2:], ["ready", "close"])

    def test_authentication_failure_marks_recipients_failed_and_closes(self) -> None:
        class FakeSMTP:
            closed = False

            def __init__(self, host, port, timeout):
                pass

            def ehlo(self):
                pass

            def starttls(self, context):
                pass

            def login(self, username, password):
                raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

            def close(self):
                self.closed = True

        fake_server = FakeSMTP("smtp.gmail.com", 587, 30)

        def smtp_factory(host, port, timeout):
            return fake_server

        contacts = [
            {"email": "one@example.com", "first_name": "One"},
            {"email": "two@example.com", "first_name": "Two"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            report_file = Path(directory) / "send_report.csv"
            results = bulk_email.send_reminders(
                contacts,
                test_settings(),
                report_file=report_file,
                smtp_factory=smtp_factory,
            )
            with report_file.open(newline="", encoding="utf-8") as file:
                report_rows = list(csv.DictReader(file))

        self.assertTrue(fake_server.closed)
        self.assertEqual([result.status for result in results], ["FAILED", "FAILED"])
        self.assertTrue(all("App Password" in result.error_message for result in results))
        self.assertEqual(len(report_rows), 2)
        self.assertTrue(all("test-app-password" not in str(row) for row in report_rows))

    def test_sends_separate_messages_and_reports_acceptance(self) -> None:
        messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                pass

            def ehlo(self):
                pass

            def starttls(self, context):
                pass

            def login(self, username, password):
                pass

            def send_message(self, message):
                messages.append(message)
                return {}

            def close(self):
                pass

        contacts = [
            {"email": "one@example.com", "first_name": "One"},
            {"email": "two@example.com", "first_name": "Two"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            report_file = Path(directory) / "send_report.csv"
            results = bulk_email.send_reminders(
                contacts,
                test_settings(),
                report_file=report_file,
                smtp_factory=FakeSMTP,
            )
            with report_file.open(newline="", encoding="utf-8") as file:
                report_rows = list(csv.DictReader(file))

        self.assertEqual([message["To"] for message in messages], [
            "one@example.com",
            "two@example.com",
        ])
        self.assertEqual([result.status for result in results], ["SENT", "SENT"])
        self.assertEqual([row["status"] for row in report_rows], ["SENT", "SENT"])
        self.assertTrue(all(row["sent_at"] for row in report_rows))

    def test_quota_error_stops_sending(self) -> None:
        attempted = []

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                pass

            def ehlo(self):
                pass

            def starttls(self, context):
                pass

            def login(self, username, password):
                pass

            def send_message(self, message):
                attempted.append(str(message["To"]))
                raise smtplib.SMTPDataError(550, b"Daily sending limit exceeded")

            def close(self):
                pass

        contacts = [
            {"email": "one@example.com", "first_name": "One"},
            {"email": "two@example.com", "first_name": "Two"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            results = bulk_email.send_reminders(
                contacts,
                test_settings(),
                report_file=Path(directory) / "send_report.csv",
                smtp_factory=FakeSMTP,
            )

        self.assertEqual(attempted, ["one@example.com"])
        self.assertEqual([result.status for result in results], ["FAILED", "FAILED"])
        self.assertTrue(all("quota error" in result.error_message for result in results))


if __name__ == "__main__":
    unittest.main()

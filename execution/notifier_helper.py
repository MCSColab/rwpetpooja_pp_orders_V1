"""
Notifier Helper Module.

Handles automated email notifications for process success or failure,
including log data in the email body.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dotenv import load_dotenv
from execution.logger_helper import LoggerHelper

load_dotenv()


class NotifierHelper:
    """Handles SMTP-based email notifications for Petpooja automation."""

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        self.smtp_host = os.getenv("SMTP_HOST")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_pass = os.getenv("SMTP_PASS")
        self.receiver = os.getenv("EMAIL_RECEIVER")

    def send_status_email(self, success: bool, log_data: Optional[str] = None) -> bool:
        """
        Send a status report email.

        Args:
            success: Whether the automation process finished successfully.
            log_data: Optional log string to include in the email body.

        Returns:
            True if email sent successfully, False otherwise.
        """
        if not all([self.smtp_host, self.smtp_user, self.smtp_pass, self.receiver]):
            self.logger.warning(
                "Email settings missing in .env. Skipping email notification."
            )
            return False

        subject = (
            "Master Order Summary Report - Successfully uploaded"
            if success
            else "Master Order Summary Report - Failed"
        )

        body = (
            f"The Petpooja automation process has completed with Status: {'SUCCESS' if success else 'FAILED'}.\n\n"
            "Process Logs:\n"
            "--------------------------------------------------\n"
        )
        if log_data:
            body += log_data
        else:
            body += "No log data provided."

        msg = MIMEMultipart()
        msg["From"] = self.smtp_user
        msg["To"] = self.receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            self.logger.info(f"Attempting to send email to {self.receiver}...")
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            self.logger.info("Email notification sent successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False


if __name__ == "__main__":
    # Test block
    notifier = NotifierHelper()
    notifier.send_status_email(True, "Standalone test log message.")

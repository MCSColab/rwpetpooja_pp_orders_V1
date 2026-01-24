"""
Notifier Helper Module.

Handles automated email notifications for process success or failure,
including log data in the email body.
"""

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

from execution.logger_helper import LoggerHelper


class NotifierHelper:
    """Handles SMTP-based email notifications for Petpooja automation."""

    def __init__(self, settings_path: str | Path = "settings.json") -> None:
        """Initialize settings from settings.json."""
        self.settings_path = Path(settings_path)
        self.settings: Dict[str, Any] = self._load_settings()
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        # Email Settings from settings.json
        self.email_enabled = self.settings.get("email_enabled", False)
        self.smtp_host = self.settings.get("smtp_host")
        self.smtp_port = int(self.settings.get("smtp_port", 587))
        self.smtp_user = self.settings.get("smtp_user")
        self.smtp_pass = self.settings.get("smtp_pass")
        self.receivers = self.settings.get("email_receivers", [])

    def _load_settings(self) -> Dict[str, Any]:
        """Load global app settings."""
        if not self.settings_path.exists():
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.error(f"Failed to load settings in NotifierHelper: {e}")
            return {}

    def send_status_email(self, success: bool, log_data: Optional[str] = None) -> bool:
        """
        Send a status report email using EmailMessage (matching reference implementation).

        Args:
            success: Whether the automation process finished successfully.
            log_data: Optional log string to include in the email body.

        Returns:
            True if email sent successfully, False otherwise.
        """
        if not self.email_enabled:
            self.logger.info("Email notification is disabled in settings.")
            return False

        if not all([self.smtp_host, self.smtp_user, self.smtp_pass, self.receivers]):
            self.logger.warning(
                "Email settings missing in settings.json. Skipping email notification."
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
        body += log_data if log_data else "No log data provided."

        # Use EmailMessage as in reference implementation
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = ", ".join(self.receivers)
        msg.set_content(body)

        try:
            self.logger.info(
                f"Attempting to send email to {', '.join(self.receivers)} via {self.smtp_host}..."
            )
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
    notifier.send_status_email(
        True, "Standalone test log message from Petpooja Automation."
    )

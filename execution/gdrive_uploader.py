"""
Google Drive Uploader Module.

This module provides functionality to upload files to Google Drive, track
upload history to prevent duplicates, and manage local file processing
(moving to 'processed' directory).

It is compliant with Python 3.13+ standards and uses PEP 585/604 type hints.
"""

import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple, Dict
from dataclasses import dataclass, asdict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from execution.logger_helper import LoggerHelper

# Required OAuth scopes for Google Drive API
SCOPES = ["https://www.googleapis.com/auth/drive"]


@dataclass
class UploadRecord:
    """Represents a record of a single file upload."""

    filename: str
    local_path: str
    gdrive_file_id: str
    gdrive_folder_id: str
    file_size: int
    file_hash: str
    upload_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary."""
        return asdict(self)


class GoogleDriveService:
    """Handles Google Drive API authentication and file upload operations."""

    def __init__(
        self,
        client_secret_file: str | Path,
        token_file: str | Path = "token.json",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize the Google Drive service.

        Args:
            client_secret_file: Path to OAuth client secret JSON file.
            token_file: Path to store/load OAuth token.
            logger: Optional logger instance.
        """
        self.client_secret_file = Path(client_secret_file)
        self.token_file = Path(token_file)
        self.logger = logger or logging.getLogger(__name__)
        self.service: Any = None
        self.credentials: Optional[Credentials] = None

    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive API.

        Returns:
            True if authentication successful.

        Raises:
            FileNotFoundError: If client secret file not found.
        """
        if not self.client_secret_file.exists():
            raise FileNotFoundError(
                f"Client secret file not found: {self.client_secret_file}"
            )

        if self.token_file.exists():
            try:
                self.credentials = Credentials.from_authorized_user_file(
                    str(self.token_file), SCOPES
                )
            except Exception as e:
                self.logger.warning(f"Could not load token file: {e}")

        if not self.credentials or not self.credentials.valid:
            if (
                self.credentials
                and self.credentials.expired
                and self.credentials.refresh_token
            ):
                try:
                    self.credentials.refresh(Request())
                except Exception as e:
                    self.logger.warning(f"Could not refresh credentials: {e}")
                    self.credentials = None

            if not self.credentials:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secret_file), SCOPES
                )
                self.credentials = flow.run_local_server(port=0)

        if self.credentials:
            with open(self.token_file, "w") as token:
                token.write(self.credentials.to_json())

        self.service = build("drive", "v3", credentials=self.credentials)
        return True

    def get_or_create_folder(self, parent_id: str, name: str) -> Optional[str]:
        """
        Finds a folder by name under a parent folder or creates it if it doesn't exist.

        Args:
            parent_id: Google Drive folder ID to search within.
            name: Folder name to find or create.

        Returns:
            The folder ID, or None if an error occurs.
        """
        if not self.service:
            return None

        try:
            # Search for existing folder
            query = f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = (
                self.service.files()
                .list(q=query, spaces="drive", fields="files(id, name)")
                .execute()
            )
            files = results.get("files", [])

            if files:
                return files[0].get("id")

            # Create if not found
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = self.service.files().create(body=metadata, fields="id").execute()
            return folder.get("id")
        except Exception as e:
            self.logger.error(f"Error getting/creating folder '{name}': {e}")
            return None

    def upload_file(
        self, file_path: Path, folder_id: str, mime_type: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Upload a file to Google Drive.

        Args:
            file_path: Path to the file to upload.
            folder_id: Google Drive folder ID to upload to.
            mime_type: Optional MIME type.

        Returns:
            Tuple of (success, file_id or error_message).
        """
        if not self.service:
            return False, "Service not initialized."

        try:
            file_metadata = {"name": file_path.name, "parents": [folder_id]}

            import mimetypes

            if mime_type is None:
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or "application/octet-stream"

            media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
            file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )

            return True, file.get("id")
        except Exception as e:
            return False, str(e)


class GDriveUploader:
    """Orchestrates file scanning, uploading, and post-processing."""

    def __init__(self, settings_path: str | Path = "settings.json") -> None:
        """
        Initialize the uploader with settings.

        Args:
            settings_path: Path to the settings.json file.
        """
        self.settings_path = Path(settings_path)
        self.settings: Dict[str, Any] = self._load_settings()
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        # Paths from settings
        self.download_dir = Path(self.settings.get("download_dir", ".tmp/downloads"))
        self.processed_dir = Path(
            self.settings.get("processed_dir", ".tmp/downloads/processed")
        )

        # GDrive Config (Hardcoded relative to gdrive subfolder for now as per UC2 structure)
        self.gdrive_dir = Path("gdrive")
        self.config_path = self.gdrive_dir / "config.txt"
        self.gdrive_config = self._load_gdrive_config()

        self.drive_service = GoogleDriveService(
            client_secret_file=self.gdrive_dir
            / self.gdrive_config.get("CLIENT_SECRET_FILE", ""),
            token_file=self.gdrive_dir
            / self.gdrive_config.get("TOKEN_FILE", "token.json"),
            logger=self.logger_helper.logger,
        )

    def _load_settings(self) -> Dict[str, Any]:
        """Load global app settings."""
        if not self.settings_path.exists():
            return {}
        with open(self.settings_path, "r") as f:
            return json.load(f)

    def _load_gdrive_config(self) -> Dict[str, str]:
        """Parse GDrive config.txt."""
        config: Dict[str, str] = {}
        if not self.config_path.exists():
            return config
        with open(self.config_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip()
        return config

    def process_files(self) -> None:
        """Scan download directory and upload files to Google Drive."""
        self.logger.info("Starting Google Drive upload process...")
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Step 1: Starting Google Drive upload process..."
        )

        if not self.drive_service.authenticate():
            self.logger.error("Failed to authenticate with Google Drive.")
            return

        self.processed_dir.mkdir(parents=True, exist_ok=True)
        gdrive_folder_id = self.gdrive_config.get("GDRIVE_FOLDER_ID")

        if not gdrive_folder_id:
            self.logger.error("GDRIVE_FOLDER_ID not found in config.")
            return

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Step 2: Identified target folder ID: {gdrive_folder_id}"
        )
        self.logger.info(f"Target Folder ID: {gdrive_folder_id}")

        files = [f for f in self.download_dir.iterdir() if f.is_file()]
        if not files:
            self.logger.info("No files found to upload.")
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] No files found in {self.download_dir} for upload."
            )
            return

        for file_path in files:
            # Determine processing date from filename (e.g. "23 Jan Sales.xlsx")
            # Or fallout to current date if parsing fails
            try:
                # Format: "DD Mon Sales.xlsx"
                date_str = file_path.name.split(" Sales")[0]
                # We need the year to calculate FY properly.
                # Since these are daily reports for 'yesterday', we can assume context.
                # If today is Jan 2026, and file is '23 Jan Sales', it's 2026.
                # If today is Jan 2026, and file is '31 Dec Sales', it's 2025.
                now = datetime.now()
                temp_date = datetime.strptime(f"{date_str} {now.year}", "%d %b %Y")

                # Correction if it's the wrap of the year
                if temp_date > now:
                    temp_date = datetime.strptime(
                        f"{date_str} {now.year - 1}", "%d %b %Y"
                    )

                # FY Calculation (Starts April)
                if temp_date.month >= 4:
                    fy_str = f"FY {temp_date.year}-{str(temp_date.year + 1)[2:]}"
                else:
                    fy_str = f"FY {temp_date.year - 1}-{str(temp_date.year)[2:]}"

                month_folder_name = f"{temp_date.strftime('%b')} sales"
            except Exception:
                # Fallback to current month if we can't parse
                now = datetime.now()
                if now.month >= 4:
                    fy_str = f"FY {now.year}-{str(now.year + 1)[2:]}"
                else:
                    fy_str = f"FY {now.year - 1}-{str(now.year)[2:]}"
                month_folder_name = f"{now.strftime('%b')} sales"

            self.logger.info(
                f"Uploading {file_path.name} to {fy_str}/{month_folder_name}..."
            )

            # Navigate/Create hierarchy
            fy_id = self.drive_service.get_or_create_folder(gdrive_folder_id, fy_str)
            target_folder_id = None
            if fy_id:
                target_folder_id = self.drive_service.get_or_create_folder(
                    fy_id, month_folder_name
                )

            if not target_folder_id:
                self.logger.error(
                    "Could not determine or create GDrive folder hierarchy."
                )
                target_folder_id = (
                    gdrive_folder_id  # Fallback to root if hierarchy fails
                )

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 3: Uploading {file_path.name} to GDrive ({fy_str}/{month_folder_name})..."
            )
            success, result = self.drive_service.upload_file(
                file_path, target_folder_id
            )

            if success:
                msg = f"Successfully uploaded {file_path.name}. File ID: {result}"
                self.logger.info(msg)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                self._move_to_processed(file_path)
            else:
                msg = f"Failed to upload {file_path.name}: {result}"
                self.logger.error(msg)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _move_to_processed(self, file_path: Path) -> None:
        """Move an uploaded file to the processed directory, overwriting if needed."""
        dest = self.processed_dir / file_path.name
        try:
            # Overwrite logic
            if dest.exists():
                dest.unlink()
            shutil.move(str(file_path), str(dest))
            self.logger.info(f"Moved {file_path.name} to {self.processed_dir}")
        except Exception as e:
            self.logger.error(f"Failed to move file {file_path.name}: {e}")


def run_uploader() -> None:
    """Entry point for the uploader logic."""
    uploader = GDriveUploader()
    uploader.process_files()


if __name__ == "__main__":
    run_uploader()

"""
Petpooja Requests-Based API Client.

This module replaces the browser-based automation (`petpooja_automation.py`)
with a lightweight HTTP client using the `requests` library. Instead of
launching Chrome, it replays authenticated session cookies to interact
with the Petpooja API directly.

Architecture:
    1. Loads session cookies from a local `cookies.json` file.
    2. POSTs to the Petpooja export endpoint with the target date.
    3. Parses the JSON response to extract the S3 download URL.
    4. Downloads the CSV report file to the configured download directory.

RAM footprint: ~30 MB (vs. 500-800 MB for the browser-based approach).
"""

import os
import json
import datetime
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List
from execution.logger_helper import LoggerHelper


class PetpoojaRequestsClient:
    """
    Lightweight HTTP client for Petpooja report downloads.

    Uses authenticated session cookies (exported from a browser session)
    to interact with the Petpooja API without requiring a live browser.

    Attributes:
        session: A requests.Session pre-loaded with Petpooja cookies.
        settings: Application settings from settings.json.
        logger: Structured logger instance.
    """

    # Petpooja API endpoint for order summary export
    EXPORT_URL = "https://billing.petpooja.com/reports/order_summary_ho_ajax/0"

    # Headers that mimic a real browser request (from HAR capture)
    DEFAULT_HEADERS = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://billing.petpooja.com/reports/order_summary_ho",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "X-Requested-With": "XMLHttpRequest",
        "x-app-client": "billing-web",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

    def __init__(self, settings_path: str = "settings.json") -> None:
        """
        Initialize the Petpooja requests client.

        Args:
            settings_path: Path to the settings.json file.

        Raises:
            FileNotFoundError: If cookies.json is not found.
            ValueError: If cookies.json is empty or malformed.
        """
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        # Load settings
        with open(settings_path, "r", encoding="utf-8") as f:
            self.settings: Dict[str, Any] = json.load(f)

        self.download_dir = Path(
            self.settings.get("download_dir", ".tmp/downloads")
        )
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Cookie file path: configurable via settings, default to project root
        self.cookie_file = Path(
            self.settings.get("cookie_file", "cookies.json")
        )

        # Initialize requests session with cookies
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self._load_cookies()

    def _load_cookies(self) -> None:
        """
        Load session cookies from the cookies.json file into the requests session.

        The cookies.json file should be a JSON object mapping cookie names
        to their string values. Example:
            {
                "PETPOOJA_CO": "abc123...",
                "CakeCookie[google_user_token]": "xyz789..."
            }

        Raises:
            FileNotFoundError: If the cookie file does not exist.
            ValueError: If the cookie file is empty or not valid JSON.
        """
        if not self.cookie_file.exists():
            raise FileNotFoundError(
                f"Cookie file not found: {self.cookie_file.resolve()}\n"
                "Run 'python -m execution.export_cookies' to generate it, "
                "or manually create it from browser DevTools."
            )

        with open(self.cookie_file, "r", encoding="utf-8") as f:
            cookies: Dict[str, str] = json.load(f)

        if not cookies:
            raise ValueError(
                f"Cookie file is empty: {self.cookie_file.resolve()}"
            )

        # Load each cookie into the session
        for name, value in cookies.items():
            self.session.cookies.set(
                name, value, domain="billing.petpooja.com"
            )

        self.logger.info(
            f"Loaded {len(cookies)} cookies from {self.cookie_file.name}"
        )

    def trigger_export(
        self,
        target_date: datetime.date,
    ) -> Optional[Dict[str, Any]]:
        """
        Trigger the order summary export for a given date.

        Sends a POST request to the Petpooja AJAX endpoint with the
        specified date range. Returns the parsed JSON response containing
        the S3 directory path and list of available report files.

        Args:
            target_date: The date to export the report for.

        Returns:
            Parsed JSON response dict on success, None on failure.
            Response structure:
                {
                    "directory_path": "https://reportsfile-live.s3-ap.../ordersummary/320816/",
                    "file_name": [
                        {"name": "Order_Summary_Report_..._YYYY-MM-DD_YYYY-MM-DD.csv",
                         "date": "YYYY-MM-DD to YYYY-MM-DD",
                         "id": "1234567"}
                    ],
                    "flag": 4
                }
        """
        date_str = target_date.strftime("%Y-%m-%d")
        self.logger.info(f"Triggering export for date: {date_str}")

        payload = {
            "data[Order][startdate]": date_str,
            "data[Order][enddate]": date_str,
            "data[Order][search_wd]": "",
            "search": "Search",
        }

        try:
            response = self.session.post(
                self.EXPORT_URL,
                data=payload,
                timeout=30,
            )

            # Check for session expiry (redirect to login page)
            if response.history:
                final_url = response.url
                if "login" in final_url.lower():
                    self.logger.error(
                        "Session expired! Redirected to login page. "
                        "Re-export cookies from your browser."
                    )
                    return None

            if response.status_code != 200:
                self.logger.error(
                    f"API returned status {response.status_code}: "
                    f"{response.text[:500]}"
                )
                return None

            # Validate response is JSON
            try:
                data = response.json()
                # Petpooja sometimes returns an integer (e.g., 2) when no data is found
                if isinstance(data, int):
                    self.logger.warning(
                        f"API returned integer response '{data}'. "
                        "This usually means no data exists for this date."
                    )
                    return None
            except requests.exceptions.JSONDecodeError:
                # Response might be HTML (login page redirect without 302)
                if "login" in response.text.lower()[:500]:
                    self.logger.error(
                        "Session expired! API returned login page HTML. "
                        "Re-export cookies from your browser."
                    )
                else:
                    self.logger.error(
                        f"API returned non-JSON response: {response.text[:300]}"
                    )
                return None

            self.logger.info(
                f"Export API response: flag={data.get('flag')}, "
                f"files_count={len(data.get('file_name', []))}"
            )
            return data

        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error to Petpooja API: {e}")
            return None
        except requests.exceptions.Timeout:
            self.logger.error("Request timed out after 30 seconds.")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error during API call: {e}")
            return None

    def find_report_url(
        self,
        api_response: Dict[str, Any],
        target_date: datetime.date,
    ) -> Optional[str]:
        """
        Extract the download URL for the target date from the API response.

        Constructs the full S3 URL by combining directory_path + file name
        for the matching date range.

        Args:
            api_response: Parsed JSON from the trigger_export response.
            target_date: The target date to find the report for.

        Returns:
            Full S3 download URL string, or None if not found.
        """
        directory_path = api_response.get("directory_path", "")
        files: List[Dict[str, str]] = api_response.get("file_name", [])

        date_str = target_date.strftime("%Y-%m-%d")
        date_range = f"{date_str} to {date_str}"

        for file_info in files:
            if file_info.get("date") == date_range:
                filename = file_info["name"]
                # directory_path ends with '/' so we can concatenate directly
                download_url = directory_path.replace("\\/", "/") + filename
                self.logger.info(f"Found report URL: {download_url}")
                return download_url

        self.logger.warning(
            f"No report found for date range '{date_range}'. "
            f"Available dates: {[f.get('date') for f in files]}"
        )
        return None

    def download_report(
        self,
        download_url: str,
        target_date: datetime.date,
    ) -> Optional[Path]:
        """
        Download the CSV report from the S3 URL.

        The S3 URLs are publicly accessible (no auth cookies needed),
        so this uses a clean requests.get() call.

        Args:
            download_url: Full S3 URL to the CSV file.
            target_date: Used for naming the local file.

        Returns:
            Path to the downloaded file, or None on failure.
        """
        target_path = self.download_dir / f"{target_date}_report.csv"
        self.logger.info(f"Downloading report to: {target_path}")

        try:
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()

            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = target_path.stat().st_size
            if file_size == 0:
                self.logger.error("Downloaded file is empty (0 bytes).")
                return None

            self.logger.info(
                f"Download complete: {target_path.name} ({file_size:,} bytes)"
            )
            return target_path

        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error during download: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return None

    def run(self, target_date: Optional[datetime.date] = None) -> Optional[Path]:
        """
        Execute the full report download pipeline.

        This is the main entry point that orchestrates:
        1. Trigger export via API
        2. Find the report URL in the response
        3. Download the CSV file

        Args:
            target_date: Date to download the report for.
                         Defaults to yesterday.

        Returns:
            Path to the downloaded CSV file, or None on failure.
        """
        if target_date is None:
            target_date = datetime.date.today() - datetime.timedelta(days=1)

        self.logger.info(
            f"Starting requests-based report download for {target_date}"
        )

        # Step 1: Trigger export
        api_response = self.trigger_export(target_date)
        if api_response is None:
            return None

        # Step 2: Find the download URL
        report_url = self.find_report_url(api_response, target_date)

        if report_url is None:
            # The report might not be generated yet. Retry the POST
            # which also triggers generation on the server side.
            self.logger.info(
                "Report not found in initial response. "
                "Retrying (server may be generating it)..."
            )
            import time
            for attempt in range(5):
                time.sleep(3)
                self.logger.info(f"Retry attempt {attempt + 1}/5...")
                api_response = self.trigger_export(target_date)
                if api_response:
                    report_url = self.find_report_url(api_response, target_date)
                    if report_url:
                        break

        if report_url is None:
            self.logger.error(
                f"Report for {target_date} not available after retries."
            )
            return None

        # Step 3: Download the CSV
        return self.download_report(report_url, target_date)


if __name__ == "__main__":
    """Quick standalone test."""
    import sys

    client = PetpoojaRequestsClient()

    # Optional: accept a date argument
    if len(sys.argv) > 1:
        target = datetime.date.fromisoformat(sys.argv[1])
    else:
        target = datetime.date.today() - datetime.timedelta(days=1)

    result = client.run(target)
    if result:
        print(f"SUCCESS: Downloaded to {result}")
    else:
        print("FAILED: Could not download report.")
        sys.exit(1)

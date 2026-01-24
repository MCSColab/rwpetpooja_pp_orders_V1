import asyncio
import os
import json
import datetime
from dotenv import load_dotenv
from execution.logger_helper import LoggerHelper
from execution.browser_helper import get_browser
from execution.file_downloader import download_file

load_dotenv()


class PetpoojaAutomation:
    def __init__(self):
        with open("settings.json", "r") as f:
            self.settings = json.load(f)

        self.logger = LoggerHelper()
        self.username = os.getenv("PETPOOJA_USERNAME")
        self.password = os.getenv("PETPOOJA_PASSWORD")

    async def run(self):
        target_date = self.get_target_date()
        self.logger.log_execution("INFO", f"Target date for processing: {target_date}")

        browser = await get_browser()
        try:
            page = await browser.get(self.settings["petpooja_url"])
            await asyncio.sleep(3)  # Wait for redirects/content
            current_url = page.url
            source = await page.get_content()
            self.logger.log_execution("INFO", f"Opened URL: {current_url}")

            # Better Login Detection: URL or Content
            is_login_page = (
                "login" in current_url.lower()
                or "sign in" in source.lower()
                or "login-wrapper" in source
            )

            if is_login_page:
                await self.handle_login(page)
                # Re-navigate or wait for dashboard
                await asyncio.sleep(5)
                if "dashboard" in page.url or "order_summary_ho" in page.url:
                    self.logger.log_execution("INFO", "Login successful.")
                    if "order_summary_ho" not in page.url:
                        page = await browser.get(self.settings["petpooja_url"])
                else:
                    self.logger.log_execution(
                        "WARNING",
                        "Might still be on login page. Trying navigation one more time...",
                    )
                    page = await browser.get(self.settings["petpooja_url"])

            # Wait for report page to load
            await asyncio.sleep(5)

            # Select Date and Export
            try:
                await self.select_date_and_export(page, target_date)
                self.logger.log_execution("INFO", "Export initiated successfully.")
            except Exception as e:
                self.logger.log_execution("ERROR", f"Failed to export: {str(e)}")
                # Capture source for debugging
                source = await page.get_content()
                with open(
                    f".tmp/error_page_{datetime.datetime.now().strftime('%H%M%S')}.html",
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(source)
                self.logger.log_execution("INFO", "Saved error page source to .tmp/")
                return

            # Capture Download Link
            download_info = await self.capture_download_link(page, target_date)
            if download_info:
                self.logger.log_execution(
                    "INFO", f"Download info captured: {download_info}"
                )
                download_url = (
                    download_info if isinstance(download_info, str) else "DYNAMIC_LINK"
                )

                target_path = f".tmp/downloads/{target_date}_report.csv"
                if download_url != "DYNAMIC_LINK" and download_url.startswith("http"):
                    print(
                        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Step 4: Initiating file download for {target_date}..."
                    )
                    success = download_file(download_url, target_path)

                    # Robust verification
                    if (
                        success
                        and os.path.exists(target_path)
                        and os.path.getsize(target_path) > 0
                    ):
                        print(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Step 5: Download completed and verified ({os.path.getsize(target_path)} bytes)."
                        )
                        self.logger.mark_date_completed(
                            target_date, target_path, download_url
                        )
                        self.logger.log_execution(
                            "INFO",
                            f"Successfully downloaded and saved record for {target_date}.",
                        )
                    else:
                        print(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ERROR: Download failed or file is empty."
                        )
                        self.logger.log_execution(
                            "ERROR",
                            f"Failed to download file for {target_date} or file is empty.",
                        )
                else:
                    # If it's a dynamic link or not a direct URL, we might need a different strategy
                    self.logger.mark_date_completed(
                        target_date, "LINK_CAPTURED_ONLY", download_url
                    )
                    self.logger.log_execution(
                        "INFO",
                        f"Saved record with captured link for {target_date} to DB.",
                    )
            else:
                self.logger.log_execution(
                    "ERROR", f"Could not find download link for {target_date}"
                )

        except Exception as e:
            self.logger.log_execution("ERROR", f"Global automation error: {str(e)}")
        finally:
            await self._cleanup_browser(browser)

    def get_target_date(self):
        """Always return yesterday's date (previous day from system date)."""
        return datetime.date.today() - datetime.timedelta(days=1)

    async def _cleanup_browser(self, browser):
        """Properly cleanup browser resources to avoid unclosed transport warnings."""
        if not browser:
            return

        try:
            # Give browser a moment to finish any pending operations
            await asyncio.sleep(0.5)

            # Close all tabs/pages first
            if hasattr(browser, "tabs") and browser.tabs:
                for tab in list(browser.tabs):
                    try:
                        await tab.close()
                    except Exception:
                        pass

            # Stop the browser
            await browser.stop()

            # Small delay to allow subprocess cleanup
            await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.log_execution("DEBUG", f"Browser cleanup notice: {str(e)}")

    async def handle_login(self, page):
        self.logger.log_execution("INFO", f"Handling login. Current URL: {page.url}")

        # Step 0: Try Google Sign-in first
        try:
            self.logger.log_execution("INFO", "Attempting Google Sign-in...")
            google_btn = await page.find("a#login_google")
            if google_btn:
                await google_btn.click()
                self.logger.log_execution(
                    "INFO", "Clicked Google Sign-in. Waiting for redirection..."
                )

                # Wait for any redirection to a Petpooja internal page
                for _ in range(15):
                    await asyncio.sleep(2)
                    current_url = page.url
                    self.logger.log_execution("INFO", f"Redirection URL: {current_url}")

                    # If we are internal (not on login/google anymore)
                    if (
                        "billing.petpooja.com" in current_url
                        and "login" not in current_url.lower()
                    ):
                        self.logger.log_execution(
                            "INFO",
                            "Google Login appears successful (internal page reached).",
                        )
                        break

                # After redirection, ensure we are on the reports page
                reports_url = self.settings.get("petpooja_url")
                if reports_url not in page.url:
                    self.logger.log_execution(
                        "INFO",
                        f"Not on reports page ({page.url}). Forcing navigation to {reports_url}",
                    )
                    await page.goto(reports_url)
                    await asyncio.sleep(5)
                    self.logger.log_execution(
                        "INFO", f"URL after forced navigation: {page.url}"
                    )

                if reports_url in page.url:
                    self.logger.log_execution(
                        "INFO", "Successfully reached reports page via Google Login."
                    )
                    return

                if "login" in page.url:
                    self.logger.log_execution(
                        "WARNING",
                        "Redirected back to login page after forced navigation. Authentication might have failed.",
                    )

            else:
                self.logger.log_execution("WARNING", "Google Sign-in button not found.")
        except Exception as e:
            self.logger.log_execution(
                "WARNING", f"Google Sign-in attempt failed: {str(e)}"
            )

        # Fallback to manual/standard login if Google Login didn't finish on reports page
        current_url = page.url
        if (
            "login" not in current_url.lower()
            and self.settings.get("petpooja_url") in current_url
        ):
            return

        self.logger.log_execution("INFO", "Proceeding with standard login fallback.")
        if not self.username or not self.password:
            self.logger.log_execution(
                "WARNING", "Credentials missing in .env. Waiting for manual login..."
            )
            # Wait for manual login (user interaction)
            for _ in range(60):
                if "dashboard" in page.url or "order_summary_ho" in page.url:
                    self.logger.log_execution(
                        "INFO", f"Manual login detected at {page.url}"
                    )
                    if self.settings.get("petpooja_url") not in page.url:
                        await page.goto(self.settings.get("petpooja_url"))
                    return
                await asyncio.sleep(1)
            self.logger.log_execution("ERROR", "Manual login timed out.")
            return

        try:
            self.logger.log_execution(
                "INFO",
                f"Attempting automated multi-step login... Current URL: {page.url}",
            )

            # Step 1: Email
            email_field = await page.find("#UserEmail") or await page.find(
                'input[name*="email"]', best_match=True
            )
            if email_field:
                await email_field.send_keys(self.username)
                continue_btn = await page.find(
                    'button[type="submit"]'
                ) or await page.find("Continue", best_match=True)
                if continue_btn:
                    await continue_btn.click()
                    await asyncio.sleep(3)
                else:
                    self.logger.log_execution("WARNING", "Continue button not found.")

            self.logger.log_execution("INFO", f"URL after Email step: {page.url}")

            # Step 2: Password
            password_field = await page.find("#UserPassword") or await page.find(
                'input[type="password"]', best_match=True
            )
            if password_field:
                await password_field.send_keys(self.password)
                signin_btn = await page.find(
                    'button[type="submit"]'
                ) or await page.find("Sign In", best_match=True)
                if signin_btn:
                    await signin_btn.click()
                    await asyncio.sleep(5)
            else:
                self.logger.log_execution(
                    "WARNING",
                    "Password field not found. Maybe it's a different login type?",
                )

            self.logger.log_execution("INFO", f"URL after Sign In: {page.url}")

            # Post-login navigation check
            if self.settings.get("petpooja_url") not in page.url:
                self.logger.log_execution(
                    "INFO",
                    f"Post-login redirect was to {page.url}. Forcing navigation to report page.",
                )
                await page.goto(self.settings.get("petpooja_url"))
                await asyncio.sleep(5)
                self.logger.log_execution(
                    "INFO", f"Final URL after forced redirect: {page.url}"
                )

        except Exception as e:
            self.logger.log_execution("WARNING", f"Automated login failed: {str(e)}")

    async def select_date_and_export(self, page, target_date):
        date_str = target_date.strftime("%Y-%m-%d")
        self.logger.log_execution("INFO", f"Selecting date: {date_str}")

        try:
            # Wait for page elements to be present
            await asyncio.sleep(2)

            # Found exact names in master_order.html
            from_date = await page.select('input[name="data[Order][startdate]"]')
            to_date = await page.select('input[name="data[Order][enddate]"]')

            if not from_date or not to_date:
                # Fallback to finding by ID or generic selectors
                from_date = await page.find("#search_dp_start input")
                to_date = await page.find("#search_dp_end input")

            if not from_date or not to_date:
                raise Exception(
                    f"Could not find date input fields. Current URL: {page.url}"
                )

            # Clear and set values
            # Using javascript to set values as they are datepickers
            await page.evaluate(
                f'document.querySelector(\'input[name="data[Order][startdate]"]\').value = "{date_str}"'
            )
            await page.evaluate(
                f'document.querySelector(\'input[name="data[Order][enddate]"]\').value = "{date_str}"'
            )

            # Found exact ID for Export button
            export_btn = await page.find("#order_searc1h") or await page.find(
                "Export", best_match=True
            )
            if not export_btn:
                raise Exception("Could not find Export button.")

            await export_btn.click()
            self.logger.log_execution("INFO", "Clicked Export button.")
        except Exception as e:
            self.logger.log_execution(
                "ERROR", f"Error in date selection/export: {str(e)}"
            )
            raise

    async def capture_download_link(self, page, target_date):
        """
        Find the download link from the reports table for the specified date.
        Table structure:
        - Table in #tbl_report with rows in #reports_data
        - Each row: <td>YYYY-MM-DD to YYYY-MM-DD</td><td><a href="url">Download</a>...</td>
        """
        date_range_str = (
            f"{target_date.strftime('%Y-%m-%d')} to {target_date.strftime('%Y-%m-%d')}"
        )
        self.logger.log_execution(
            "INFO", f"Waiting for download link for range: {date_range_str}"
        )

        for attempt in range(30):
            try:
                # Use JavaScript to find the exact row and extract the download URL
                js_code = f'''
                (() => {{
                    const rows = document.querySelectorAll('#reports_data tr');
                    for (const row of rows) {{
                        const dateCell = row.querySelector('td:first-child');
                        if (dateCell && dateCell.textContent.trim() === "{date_range_str}") {{
                            const link = row.querySelector('a[href*="s3"]');
                            if (link) {{
                                return link.href;
                            }}
                        }}
                    }}
                    return null;
                }})()
                '''
                download_url = await page.evaluate(js_code)

                if download_url:
                    self.logger.log_execution(
                        "INFO", f"Found download URL: {download_url}"
                    )
                    return download_url

                # Check if the date range exists in page but link not ready yet
                source = await page.get_content()
                if date_range_str not in source:
                    self.logger.log_execution(
                        "DEBUG",
                        f"Date range {date_range_str} not yet in table (attempt {attempt + 1})",
                    )

            except asyncio.CancelledError:
                raise  # Don't suppress cancellation
            except Exception as e:
                if attempt < 3:
                    self.logger.log_execution(
                        "DEBUG", f"Download link check attempt {attempt + 1}: {str(e)}"
                    )

            await asyncio.sleep(1)

        return None


if __name__ == "__main__":
    import warnings

    # Suppress transport warnings during cleanup (harmless on Windows)
    warnings.filterwarnings("ignore", category=ResourceWarning)

    automation = PetpoojaAutomation()
    asyncio.run(automation.run())

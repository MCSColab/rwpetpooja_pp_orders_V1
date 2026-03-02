"""
Petpooja Report Data Cleaner Module.

This module provides functionality to clean and transform Excel reports
downloaded from Petpooja, following specific business logic for normalization,
filtering, and standardization.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
from execution.logger_helper import LoggerHelper


class DataCleaner:
    """Handles cleaning and transformation of Petpooja Excel reports."""

    def __init__(self, settings_path: str | Path = "settings.json") -> None:
        """
        Initialize the DataCleaner.

        Args:
            settings_path: Path to the settings.json file.
        """
        self.settings_path = Path(settings_path)
        self.settings: Dict[str, Any] = self._load_settings()
        self.logger_helper = LoggerHelper()
        self.logger = self.logger_helper.logger

        self.download_dir = Path(self.settings.get("download_dir", ".tmp/downloads"))
        self.processed_dir = Path(
            self.settings.get("processed_dir", self.download_dir / "processed")
        )
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_processed_files()

    def _cleanup_processed_files(self) -> None:
        """Remove processed files older than 30 days."""
        try:
            thirty_days_ago = datetime.now().timestamp() - (30 * 24 * 60 * 60)
            removed_count = 0
            
            for file_path in self.processed_dir.glob("*"):
                if file_path.is_file():
                    if file_path.stat().st_mtime < thirty_days_ago:
                        file_path.unlink()
                        removed_count += 1
            
            if removed_count > 0:
                self.logger.info(f"Cleaned up {removed_count} processed files older than 30 days.")
        except Exception as e:
            self.logger.error(f"Failed to cleanup processed files: {e}")

    def clear_download_dir(self) -> None:
        """Forcefully remove any existing XLSX or CSV files from the downloads directory."""
        try:
            removed_count = 0
            for file_path in self.download_dir.glob("*"):
                if file_path.is_file() and file_path.suffix.lower() in [".csv", ".xlsx"]:
                    file_path.unlink()
                    removed_count += 1
            if removed_count > 0:
                self.logger.info(f"Purged {removed_count} stale files from downloads directory.")
        except Exception as e:
            self.logger.error(f"Failed to clear download directory: {e}")

    def _load_settings(self) -> Dict[str, Any]:
        """Load global app settings."""
        if not self.settings_path.exists():
            return {}
        with open(self.settings_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def process_latest_report(self) -> Optional[Path]:
        """
        Find and process the latest report in the download directory.

        Returns:
            Path to the cleaned report, or None if no report found.
        """
        # Find all .csv or .xlsx files in download_dir
        files = [
            f
            for f in self.download_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in [".csv", ".xlsx"]
            and f.parent == self.download_dir  # Don't look in subdirectories
        ]

        if not files:
            self.logger.info("No reports found in download directory to clean.")
            return None

        # Sort by modification time to get the latest
        latest_file = max(files, key=lambda f: f.stat().st_mtime)
        self.logger.info(f"Processing report: {latest_file.name}")

        try:
            # 1. Read the data
            self.logger.info(f"Reading input file: {latest_file.name}...")
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 1: Reading input file..."
            )
            if latest_file.suffix.lower() == ".csv":
                df = pd.read_csv(latest_file)
            else:
                df = pd.read_excel(latest_file)

            # 2. Transformation Logic
            cleaned_df = self._transform_data(df)

            # 3. Save the cleaned file
            # Extract date from filename if possible (format: YYYY-MM-DD_report.csv)
            try:
                date_part = latest_file.name.split("_")[0]
                processing_datetime = datetime.strptime(date_part, "%Y-%m-%d")
            except Exception:
                self.logger.warning(
                    f"Could not parse date from filename {latest_file.name}. Using today's date."
                )
                processing_datetime = datetime.now()

            output_filename = processing_datetime.strftime("%d %b Sales.xlsx")
            output_path = self.download_dir / output_filename

            self.logger.info(f"Saving cleaned report to: {output_path.name}...")
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 4: Saving output file as {output_filename}..."
            )
            cleaned_df.to_excel(output_path, index=False)

            # 4. Move original to processed folder
            dest = self.processed_dir / latest_file.name
            try:
                # Robust overwrite move for Windows
                if dest.exists():
                    try:
                        dest.unlink()
                    except Exception as unlink_err:
                        self.logger.warning(f"Could not unlink existing file {dest}: {unlink_err}")
                
                # Perform the move using shutil.move which is safer across drives, 
                # but we've handled the target deletion to ensure it's overwritten.
                shutil.move(str(latest_file), str(dest))
                self.logger.info(f"Moved original file to processed folder: {dest}")
            except Exception as move_err:
                self.logger.error(f"Failed to move file to processed: {move_err}")

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 5: Archiving original file."
            )

            return output_path

        except Exception as e:
            self.logger.error(f"Error cleaning report {latest_file.name}: {e}")
            return None

    def _transform_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply transformation logic to the dataframe.

        Args:
            df: Original dataframe.

        Returns:
            Transformed dataframe.
        """
        # Create a copy to avoid SettingWithCopyWarning
        df = df.copy()

        # --- A. Column Normalization ---
        if "order_type" in df.columns:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 2a: Normalizing order types..."
            )
            # Update "Delivery(Parcel)" or "Delivery (Parcel)" to exactly "Delivery"
            mask = df["order_type"].str.contains(
                r"Delivery\s?\(Parcel\)", case=False, na=False
            )
            df.loc[mask, "order_type"] = "Delivery"

        # --- B. Record Filtering ---
        if "status" in df.columns:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 2b: Filtering cancelled/complimentary and staff records..."
            )
            # Delete rows where status is "Cancelled" or "Complimentary"
            df = df[~df["status"].str.lower().isin(["cancelled", "complimentary"])]

            # Remove Staff: Delete all rows where any key column contains "Staff"
            cols_to_check = ["status", "order_type", "sub_order_type"]
            for col in cols_to_check:
                if col in df.columns:
                    df = df[df[col].astype(str).str.lower() != "staff"]

        # --- C. Platform Standardization ---
        if "sub_order_type" in df.columns:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Step 2c: Standardizing platforms (Swiggy, Zomato, App)..."
            )
            # Standardize Swiggy
            swiggy_mask = df["sub_order_type"].str.contains(
                "Swiggy", case=False, na=False
            )
            df.loc[swiggy_mask, "sub_order_type"] = "Swiggy"

            # Standardize Zomato
            zomato_mask = df["sub_order_type"].str.contains(
                "Zomato", case=False, na=False
            )
            df.loc[zomato_mask, "sub_order_type"] = "Zomato"

            # Standardize FUDR Online
            fudr_mask = df["sub_order_type"].str.contains(
                "Fudr Online", case=False, na=False
            )
            df.loc[fudr_mask, "sub_order_type"] = "FUDR Online"

            # Map App: Change "FUDR Online" to "App"
            df.loc[df["sub_order_type"] == "FUDR Online", "sub_order_type"] = "App"

        # --- D. Conditional Logic ---
        if "sub_order_type" in df.columns and "order_type" in df.columns:
            # If sub_order_type is "App" AND order_type is "Delivery", change sub_order_type to "Delivery"
            app_delivery_mask = (df["sub_order_type"] == "App") & (
                df["order_type"] == "Delivery"
            )
            df.loc[app_delivery_mask, "sub_order_type"] = "Delivery"

            # Map non-standard platforms to order_type
            known_platforms = [
                "Swiggy",
                "Zomato",
                "Delivery",
                "App",
                "Dine In",
                "Takeaway",
            ]
            b2b_mask = ~df["sub_order_type"].isin(known_platforms)
            df.loc[b2b_mask, "sub_order_type"] = df.loc[b2b_mask, "order_type"]

        # --- 3. Data Pruning ---
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Step 3: Pruning non-essential columns..."
        )
        cols_to_delete = [
            "gst_no",
            "payment_description",
            "virtual_brand_name",
            "assign_to",
            "group_name",
            "customer_phone",
            "persons",
            "order_cancel_reason",
        ]
        df = df.drop(columns=[c for c in cols_to_delete if c in df.columns])

        # --- 4. Final Output Requirements ---
        # Ensure financial columns remain numeric
        financial_cols = [
            "my_amount",
            "total_tax",
            "discount",
            "delivery_charge",
            "container_charge",
            "service_charge",
            "additional_charge",
            "waived_off",
            "round_off",
            "total",
        ]
        for col in financial_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        return df


def run_cleaner() -> None:
    """Entry point for testing the cleaner."""
    cleaner = DataCleaner()
    cleaner.process_latest_report()


if __name__ == "__main__":
    run_cleaner()

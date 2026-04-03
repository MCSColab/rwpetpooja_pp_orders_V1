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
        Apply transformation logic to the dataframe to match the 42-column
        CamelCase database schema.

        Args:
            df: Original dataframe from Petpooja report.

        Returns:
            Transformed dataframe with calculated metrics and mapped headers.
        """
        self.logger.info("Initializing Data Transformation & Business Logic...")
        df = df.copy()

        # 1. Column Normalization (Pre-Mapping)
        if "order_type" in df.columns:
            mask = df["order_type"].str.contains(r"Delivery\s?\(Parcel\)", case=False, na=False)
            df.loc[mask, "order_type"] = "Delivery"

        # 2. Filtering
        if "status" in df.columns:
            df = df[~df["status"].str.lower().isin(["cancelled", "complimentary"])]
            for col in ["status", "order_type", "sub_order_type"]:
                if col in df.columns:
                    df = df[df[col].astype(str).str.lower() != "staff"]

        # 3. Platform Standardization
        if "sub_order_type" in df.columns:
            df.loc[df["sub_order_type"].str.contains("Swiggy", case=False, na=False), "sub_order_type"] = "Swiggy"
            df.loc[df["sub_order_type"].str.contains("Zomato", case=False, na=False), "sub_order_type"] = "Zomato"
            df.loc[df["sub_order_type"].str.contains("Fudr Online", case=False, na=False), "sub_order_type"] = "App"
            
            # Map App to Delivery if order_type is Delivery
            if "order_type" in df.columns:
                mask = (df["sub_order_type"] == "App") & (df["order_type"] == "Delivery")
                df.loc[mask, "sub_order_type"] = "Delivery"

                # Map unknown to order_type
                known = ["Swiggy", "Zomato", "Delivery", "App", "Dine In", "Takeaway"]
                b2b_mask = ~df["sub_order_type"].isin(known)
                df.loc[b2b_mask, "sub_order_type"] = df.loc[b2b_mask, "order_type"]

        # 4. Mandatory Numeric Conversion
        financial_input_cols = [
            "my_amount", "total_tax", "discount", "delivery_charge", 
            "container_charge", "service_charge", "additional_charge", 
            "waived_off", "round_off", "total"
        ]
        for col in financial_input_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(2)

        # 5. Header Mapping (Raw -> DB)
        header_map = {
            'restaurant_name': 'Outlet_Name',
            'invoice_no': 'Invoice_No',
            'gst_no': 'GST_No',
            'date': 'Date',
            'kot_no': 'Kot_No',
            'payment_type': 'Payment_Type',
            'payment_description': 'Payment_Description',
            'order_type': 'Order_Type',
            'status': 'Status',
            'sub_order_type': 'Platform',
            'area': 'Area',
            'virtual_brand_name': 'Virtual_Brand_Name',
            'assign_to': 'Assign_To',
            'group_name': 'Group_Name',
            'customer_phone': 'Customer_Phone',
            'customer_name': 'Customer_Name',
            'customer_address': 'Customer_Address',
            'customer_locality': 'Customer_Locality',
            'persons': 'Persons',
            'order_cancel_reason': 'Order_Cancel_Reason',
            'my_amount': 'Base_Price',
            'total_tax': 'Gst',
            'discount': 'Discount',
            'delivery_charge': 'Delivery_Charge',
            'container_charge': 'Container_Charge',
            'service_charge': 'Service_Charge',
            'additional_charge': 'Additional_Charge',
            'waived_off': 'Waived_Off',
            'round_off': 'Round_Off',
            'total': 'Customer_Paid'
        }
        df = df.rename(columns=header_map)

        # 6. Type Normalization & Null placeholders
        self.logger.info("Standardizing types and initializing blank metrics...")
        
        # Ensure Date is properly typed for the standard schema
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])

        # Business Logic requirement: All columns after Customer_Paid should be left blank (nil)
        columns_after_paid = [
            'Net Sales', 'Quantity', 'AOV', 'Zone', 'Sales Type', 'GMV',
            'Total Sales', 'Sales Month', 'Discount %', 'Financial Year',
            'Quarter', 'Sales Category'
        ]
        
        for col in columns_after_paid:
            df[col] = None
        
        self.logger.info("Extended columns (post-Customer_Paid) successfully nullified.")

        # Final Cleanup: Remove columns not in the target DB schema if they exist
        target_schema_cols = [
            'Outlet_Name', 'Invoice_No', 'GST_No', 'Date', 'Kot_No', 'Payment_Type',
            'Payment_Description', 'Order_Type', 'Status', 'Platform', 'Area',
            'Virtual_Brand_Name', 'Assign_To', 'Group_Name', 'Customer_Phone',
            'Customer_Name', 'Customer_Address', 'Customer_Locality', 'Persons',
            'Order_Cancel_Reason', 'Base_Price', 'Gst', 'Discount', 'Delivery_Charge',
            'Container_Charge', 'Service_Charge', 'Additional_Charge', 'Waived_Off',
            'Round_Off', 'Customer_Paid', 'Net Sales', 'Quantity', 'AOV', 'Zone',
            'Sales Type', 'GMV', 'Total Sales', 'Sales Month', 'Discount %',
            'Financial Year', 'Quarter', 'Sales Category'
        ]
        
        # Add missing columns with nulls to ensure insert doesn't fail on missing keys
        for col in target_schema_cols:
            if col not in df.columns:
                df[col] = None

        self.logger.info(f"Transformation complete. DataFrame shape: {df.shape}")
        return df[target_schema_cols]


def run_cleaner() -> None:
    """Entry point for testing the cleaner."""
    cleaner = DataCleaner()
    cleaner.process_latest_report()


if __name__ == "__main__":
    run_cleaner()

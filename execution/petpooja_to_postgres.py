"""
Petpooja to PostgreSQL Integration Pipeline.

This script orchestrates the full flow:
1. Downloads the report from Petpooja using Chrome automation.
2. Cleans and transforms the data using pandas.
3. Inserts/Upserts the records into the Amazon Lightsail PostgreSQL database.
4. Archives the processed files locally.
"""

import asyncio
import os
import sys
import datetime
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Ensure the root directory is in the path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from execution.petpooja_automation import PetpoojaAutomation
from execution.data_cleaner import DataCleaner
from execution.pgsql_uploader import PostgresUploader
from execution.logger_helper import LoggerHelper

async def run_pipeline():
    """Main pipeline execution logic."""
    logger_helper = LoggerHelper()
    logger = logger_helper.logger
    
    logger.info("Starting Petpooja to PostgreSQL Pipeline...")
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] PIPELINE START")

    # Step 1: Download the report
    logger.info("Step 1: Downloading report from Petpooja...")
    automation = PetpoojaAutomation()
    await automation.run()
    
    # Step 2: Clean and transform the data
    logger.info("Step 2: Cleaning and transforming downloaded data...")
    cleaner = DataCleaner()
    # process_latest_report returns the Path to the cleaned XLSX file
    # but more importantly, we want the dataframe. 
    # I'll modify DataCleaner slightly or just read the saved XLSX back.
    # Actually, process_latest_report moves the original to 'processed'.
    output_xlsx_path = cleaner.process_latest_report()
    
    if not output_xlsx_path or not output_xlsx_path.exists():
        logger.error("Failed to produce a cleaned report. Aborting pipeline.")
        return

    # Step 3: Insert into PostgreSQL
    logger.info(f"Step 3: Inserting records from {output_xlsx_path.name} into PostgreSQL...")
    try:
        # Read the cleaned XLSX file back into a DataFrame
        df = pd.read_excel(output_xlsx_path)
        
        # Initialize Uploader
        uploader = PostgresUploader()
        
        # Insert records
        success = uploader.insert_dataframe(df)
        
        if success:
            logger.info("Pipeline completed successfully. Data is now in PostgreSQL.")
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] PIPELINE SUCCESS")
        else:
            logger.error("Failed to insert records into PostgreSQL.")
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] PIPELINE FAILED AT INSERTION")
            
    except Exception as e:
        logger.error(f"Error during database insertion: {e}")
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] CRITICAL ERROR: {e}")

    # Note: GDrive upload is skipped as per user request.
    # logger.info("Step 4: [SKIPPED] Google Drive upload (No longer required).")

if __name__ == "__main__":
    # Suppress transport warnings on Windows
    import warnings
    warnings.filterwarnings("ignore", category=ResourceWarning)
    
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
    except Exception as e:
        print(f"\nPipeline crashed: {e}")

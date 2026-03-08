from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def fix():
    uploader = PostgresUploader()
    with uploader.engine.begin() as conn:
        print("Cleaning duplicates...")
        conn.execute(text('DELETE FROM zohoanalytics."P_orders" a USING zohoanalytics."P_orders" b WHERE a.ctid < b.ctid AND a.invoice_no = b.invoice_no;'))
        
        print("Adding UNIQUE INDEX...")
        conn.execute(text('CREATE UNIQUE INDEX p_orders_invoice_no_unique_idx ON zohoanalytics."P_orders" (invoice_no);'))
        print("Index added.")

if __name__ == "__main__":
    fix()

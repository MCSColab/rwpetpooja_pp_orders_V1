from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def fix():
    uploader = PostgresUploader()
    with uploader.engine.begin() as conn:
        print("Final attempt to force primary key...")
        conn.execute(text('DELETE FROM zohoanalytics."P_orders" a USING zohoanalytics."P_orders" b WHERE a.ctid < b.ctid AND a.invoice_no = b.invoice_no;'))
        conn.execute(text('ALTER TABLE zohoanalytics."P_orders" ADD PRIMARY KEY (invoice_no);'))
        print("Primary Key added.")

if __name__ == "__main__":
    fix()

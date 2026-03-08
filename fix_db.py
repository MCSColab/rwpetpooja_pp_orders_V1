from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def fix():
    uploader = PostgresUploader()
    with uploader.engine.connect() as conn:
        print("Checking for duplicates before adding constraint...")
        check_dupes = text('SELECT invoice_no, COUNT(*) FROM zohoanalytics."P_orders" GROUP BY invoice_no HAVING COUNT(*) > 1')
        dupes = conn.execute(check_dupes).fetchall()
        if dupes:
            print(f"Found {len(dupes)} duplicate invoice numbers. Cleaning up...")
            # Keep only one instance of each invoice_no
            cleanup = text('''
                DELETE FROM zohoanalytics."P_orders" a
                USING zohoanalytics."P_orders" b
                WHERE a.ctid < b.ctid
                AND a.invoice_no = b.invoice_no;
            ''')
            conn.execute(cleanup)
            print("Cleanup complete.")
        
        print("Adding unique constraint on invoice_no...")
        add_constraint = text('ALTER TABLE zohoanalytics."P_orders" ADD CONSTRAINT p_orders_invoice_no_key UNIQUE (invoice_no);')
        conn.execute(add_constraint)
        print("Constraint added successfully.")

if __name__ == "__main__":
    fix()

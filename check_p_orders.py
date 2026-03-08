from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def check():
    uploader = PostgresUploader()
    with uploader.engine.connect() as conn:
        print("Checking table structure...")
        query = text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'zohoanalytics' 
            AND table_name = 'P_orders';
        """)
        result = conn.execute(query)
        for row in result:
            print(row)

if __name__ == "__main__":
    check()

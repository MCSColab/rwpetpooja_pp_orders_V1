from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def check():
    uploader = PostgresUploader()
    with uploader.engine.connect() as conn:
        print("Checking column names...")
        res = conn.execute(text('SELECT column_name FROM information_schema.columns WHERE table_schema = \'zohoanalytics\' AND table_name = \'P_orders\';'))
        for row in res:
            print(row)
            
        print("\nChecking unique constraints/indexes on P_orders...")
        query = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'zohoanalytics'
            AND tablename = 'P_orders';
        """)
        result = conn.execute(query)
        for row in result:
            print(row)

if __name__ == "__main__":
    check()

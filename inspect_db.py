from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def inspect():
    uploader = PostgresUploader()
    with uploader.engine.connect() as conn:
        print("Checking constraints...")
        query = text("""
            SELECT conname, pg_get_constraintdef(c.oid) 
            FROM pg_constraint c 
            JOIN pg_namespace n ON n.oid = c.connamespace 
            WHERE n.nspname = 'zohoanalytics' 
            AND conrelid = 'zohoanalytics."P_orders"'::regclass;
        """)
        result = conn.execute(query)
        for row in result:
            print(row)
            
        print("\nChecking indices...")
        query_idx = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'zohoanalytics'
            AND tablename = 'P_orders';
        """)
        result_idx = conn.execute(query_idx)
        for row in result_idx:
            print(row)

if __name__ == "__main__":
    inspect()

from execution.pgsql_uploader import PostgresUploader
from sqlalchemy import text

def verify():
    uploader = PostgresUploader()
    with uploader.engine.connect() as conn:
        print("Checking all constraints for P_orders...")
        query = text("""
            SELECT
                tc.constraint_name, tc.table_name, kcu.column_name, 
                tc.constraint_type
            FROM 
                information_schema.table_constraints AS tc 
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'zohoanalytics' AND tc.table_name = 'P_orders';
        """)
        result = conn.execute(query)
        for row in result:
            print(row)

if __name__ == "__main__":
    verify()

# PostgreSQL Conflict Error Analysis

## Error Summary
**Date:** March 8, 2026
**Error Type:** `psycopg2.errors.InvalidColumnReference`
**Message:** `there is no unique or exclusion constraint matching the ON CONFLICT specification`

## The Problem
The Petpooja automation pipeline fails during the PostgreSQL upload phase. The code uses an `UPSERT` logic (INSERT ... ON CONFLICT DO UPDATE) targeting the `invoice_no` column. Despite several attempts to add a `UNIQUE CONSTRAINT` and a `UNIQUE INDEX` to the `zohoanalytics.P_orders` table, PostgreSQL continues to claim that no matching constraint exists for the `ON CONFLICT` clause.

## Exact SQL Query Being Executed
```sql
INSERT INTO zohoanalytics."P_orders" (
    restaurant_name, invoice_no, date, kot_no, payment_type, order_type, 
    status, sub_order_type, area, customer_name, customer_address, 
    customer_locality, my_amount, total_tax, discount, delivery_charge, 
    container_charge, service_charge, additional_charge, waived_off, 
    round_off, total
)
SELECT 
    restaurant_name, invoice_no, CAST(date AS DATE), kot_no, payment_type, 
    order_type, status, sub_order_type, area, customer_name, 
    customer_address, customer_locality, my_amount, total_tax, discount, 
    delivery_charge, container_charge, service_charge, additional_charge, 
    waived_off, round_off, total 
FROM temp_orders
ON CONFLICT (invoice_no)
DO UPDATE SET 
    restaurant_name = EXCLUDED.restaurant_name, 
    date = EXCLUDED.date, 
    kot_no = EXCLUDED.kot_no, 
    payment_type = EXCLUDED.payment_type, 
    order_type = EXCLUDED.order_type, 
    status = EXCLUDED.status, 
    sub_order_type = EXCLUDED.sub_order_type, 
    area = EXCLUDED.area, 
    customer_name = EXCLUDED.customer_name, 
    customer_address = EXCLUDED.customer_address, 
    customer_locality = EXCLUDED.customer_locality, 
    my_amount = EXCLUDED.my_amount, 
    total_tax = EXCLUDED.total_tax, 
    discount = EXCLUDED.discount, 
    delivery_charge = EXCLUDED.delivery_charge, 
    container_charge = EXCLUDED.container_charge, 
    service_charge = EXCLUDED.service_charge, 
    additional_charge = EXCLUDED.additional_charge, 
    waived_off = EXCLUDED.waived_off, 
    round_off = EXCLUDED.round_off, 
    total = EXCLUDED.total;
```

## Table Schema (zohoanalytics.P_orders)
| Column | Type |
| :--- | :--- |
| invoice_no | text |
| restaurant_name | text |
| date | date |
| kot_no | text |
| payment_type | text |
| order_type | text |
| status | text |
| sub_order_type | text |
| area | text |
| customer_name | text |
| customer_address | text |
| customer_locality | text |
| my_amount | bigint |
| total_tax | double precision |
| discount | bigint |
| delivery_charge | bigint |
| container_charge | double precision |
| service_charge | bigint |
| additional_charge | bigint |
| waived_off | bigint |
| round_off | double precision |
| total | bigint |

## Attempted Fixes (All failed to resolve the runtime error)
1.  **Unique Constraint:** Ran `ALTER TABLE zohoanalytics."P_orders" ADD CONSTRAINT p_orders_invoice_no_key UNIQUE (invoice_no);` after cleaning duplicates.
2.  **Unique Index:** Ran `CREATE UNIQUE INDEX p_orders_invoice_no_unique_idx ON zohoanalytics."P_orders" (invoice_no);`.
3.  **Verification:** Queried `information_schema.table_constraints` and `pg_indexes`. Curiously, the verification scripts often returned empty results even after the `CREATE` commands reported success.

## Environment Details
- **Runtime:** Python 3.12 (on AWS Lightsail Debian/Ubuntu)
- **Database:** PostgreSQL (AWS RDS/Lightsail managed)
- **Driver:** `psycopg2-binary`
- **ORM/Tool:** `SQLAlchemy` 2.0+

import psycopg2
from dotenv import load_dotenv

load_dotenv()
import os

CONNECTION_STRING = os.getenv("CONNECTION_STRING")


def get_connection(connection_string: str | None = None):
    dsn = connection_string or CONNECTION_STRING
    if not dsn:
        raise ValueError(
            "Postgres connection string is required "
            "(pass connection_string or set CONNECTION_STRING)."
        )
    return psycopg2.connect(dsn)


def get_schemas(cursor):
    cursor.execute("""
        SELECT schema_name 
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
        ORDER BY schema_name;
    """)
    return [row[0] for row in cursor.fetchall()]


def get_tables(cursor, schema_name):
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name;
    """, (schema_name,))
    return [row[0] for row in cursor.fetchall()]


def prompt_for_schema(schemas):
    print("Available tenants/schemas:")
    for idx, schema in enumerate(schemas, start=1):
        print(f"  {idx}. {schema}")

    choice = input("\nSelect a tenant (number): ").strip()

    try:
        return schemas[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return None


if __name__ == "__main__":
    connection = get_connection()
    cursor = connection.cursor()

    schemas = get_schemas(cursor)
    selected_schema = prompt_for_schema(schemas)

    if selected_schema:
        tables = get_tables(cursor, selected_schema)

        print(f"\n=== Tables in '{selected_schema}' ===")
        for table in tables:
            print(f"  - {table}")
        print(f"len(tables) = {len(tables)}")

    cursor.close()
    connection.close()
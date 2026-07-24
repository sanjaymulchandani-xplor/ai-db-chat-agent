import asyncio
import aiosqlite
from database.postgres_connection import get_connection, get_schemas, get_tables, prompt_for_schema

SQLITE_DB = "schema_store.db"

# Blocking Postgres work - run in an executor from async code.
def fetch_schema_and_tables():
    connection = get_connection()
    cursor = connection.cursor()

    schemas = get_schemas(cursor)
    selected_schema = prompt_for_schema(schemas)

    tables = []
    if selected_schema:
        tables = get_tables(cursor, selected_schema)

    cursor.close()
    connection.close()

    return selected_schema, tables


async def init_db(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_name TEXT NOT NULL,
            table_name TEXT NOT NULL,
            full_name TEXT NOT NULL UNIQUE
        );
    """)
    await db.commit()


async def save_tables(schema_name, tables):
    async with aiosqlite.connect(SQLITE_DB) as db:
        await init_db(db)

        rows = [(schema_name, table, f"{schema_name}.{table}") for table in tables]

        await db.executemany("""
            INSERT OR IGNORE INTO schema_tables (schema_name, table_name, full_name)
            VALUES (?, ?, ?);
        """, rows)

        await db.commit()
        print(f"\nSaved {len(rows)} tables for schema '{schema_name}' into {SQLITE_DB}")


async def main():
    loop = asyncio.get_event_loop()

    # Run blocking psycopg2 + input() call in a thread
    selected_schema, tables = await loop.run_in_executor(None, fetch_schema_and_tables)

    if not selected_schema:
        print("No schema selected, exiting.")
        return

    await save_tables(selected_schema, tables)


if __name__ == "__main__":
    asyncio.run(main())
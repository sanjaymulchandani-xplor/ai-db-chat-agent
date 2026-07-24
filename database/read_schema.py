import asyncio
import aiosqlite

SQLITE_DB = "schema_store.db"


async def get_all_schemas(db):
    async with db.execute("""
        SELECT DISTINCT schema_name FROM schema_tables ORDER BY schema_name;
    """) as cursor:
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_tables_for_schema(db, schema_name):
    async with db.execute("""
        SELECT table_name, full_name FROM schema_tables
        WHERE schema_name = ?
        ORDER BY table_name;
    """, (schema_name,)) as cursor:
        return await cursor.fetchall()


async def get_all_tables(db):
    async with db.execute("""
        SELECT schema_name, table_name, full_name FROM schema_tables
        ORDER BY schema_name, table_name;
    """) as cursor:
        return await cursor.fetchall()


async def main():
    async with aiosqlite.connect(SQLITE_DB) as db:
        schemas = await get_all_schemas(db)

        if not schemas:
            print("No data found in schema_store.db. Run save_schema.py first.")
            return

        print("Stored tenants/schemas:")
        for idx, schema in enumerate(schemas, start=1):
            print(f"  {idx}. {schema}")
        print(f"  {len(schemas) + 1}. Show all")

        choice = input("\nSelect a tenant to view (number): ").strip()

        try:
            choice_num = int(choice)
        except ValueError:
            print("Invalid selection.")
            return

        if choice_num == len(schemas) + 1:
            rows = await get_all_tables(db)
            print(f"\n=== All stored tables ({len(rows)}) ===")
            for schema_name, table_name, full_name in rows:
                print(f"  - {full_name}")
        elif 1 <= choice_num <= len(schemas):
            selected_schema = schemas[choice_num - 1]
            rows = await get_tables_for_schema(db, selected_schema)
            print(f"\n=== Tables in '{selected_schema}' ({len(rows)}) ===")
            for table_name, full_name in rows:
                print(f"  - {full_name}")
        else:
            print("Invalid selection.")


if __name__ == "__main__":
    asyncio.run(main())
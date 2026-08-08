# TradePilot AI — manual database initialization script.
#
# Run this to create database/tradepilot.db (if it doesn't exist yet) and
# confirm the schema builds without errors:
#
#   python -m database.init_db
#
# Safe to run again later — it never deletes or overwrites existing data.

from database.database import Base, engine, init_db


def main() -> None:
    init_db()
    table_names = sorted(Base.metadata.tables.keys())
    print(f"Database ready at: {engine.url}")
    print("Tables:")
    for name in table_names:
        print(f"  - {name}")


if __name__ == "__main__":
    main()

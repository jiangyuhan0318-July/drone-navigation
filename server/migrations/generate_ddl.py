"""Regenerate the table DDL for migrations/001_init_auth_schema.sql.

Prints CreateTable/CreateIndex statements compiled with the PostgreSQL
dialect, straight from the live SQLAlchemy models — so the migration script
can never silently drift from what the app expects.

Usage:
    cd server && /path/to/venv/bin/python -m migrations.generate_ddl

Then paste the output into section 3 of 001_init_auth_schema.sql
(keep the hand-added DEFAULT '{}'::jsonb on user_settings.settings).
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import MatrixAccount, OAuthAccount, User, UserSettings


def main() -> None:
    dialect = postgresql.dialect()
    for table in (User.__table__, OAuthAccount.__table__, UserSettings.__table__, MatrixAccount.__table__):
        print(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).rstrip(";") + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            print(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)).rstrip(";") + ";")
        print()


if __name__ == "__main__":
    main()

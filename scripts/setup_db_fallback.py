"""Provision optional read-only AI views/account, without editing .env or business data.
Run from the AI folder using the same venv as run.py.
"""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import re
import sys

import pymysql
from dotenv import dotenv_values

VIEWS = (
    "inventory_db.ai_equipment", "inventory_db.ai_warehouses",
    "inventory_db.ai_available_equipment", "inventory_db.ai_reservation_blocks",
    "rental_db.ai_quotations", "rental_db.ai_rental_orders", "rental_db.ai_rental_requests",
    "rental_db.ai_rental_contracts", "organization_customer_db.ai_customers",
)


def main():
    parser = argparse.ArgumentParser(description="Create AI read-only views and account (no seed reset)")
    parser.add_argument("--backend-env", type=Path, required=True)
    parser.add_argument("--ai-env", type=Path, default=Path(".env"))
    args = parser.parse_args()
    backend = dotenv_values(args.backend_env)
    ai = dotenv_values(args.ai_env)
    username = ai.get("AI_DB_USER") or "equipment_ai_reader"
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{2,31}", username) or username.casefold() == "root":
        raise ValueError("AI_DB_USER must be a separate read-only account")
    password = os.environ.get("AI_DB_PASSWORD") or ai.get("AI_DB_PASSWORD") or getpass("Password for AI reader (put the same value in AI .env): ")
    if len(password) < 12:
        raise ValueError("AI_DB_PASSWORD must contain at least 12 characters")
    root_password = backend.get("MYSQL_ROOT_PASSWORD")
    if not root_password:
        raise ValueError("MYSQL_ROOT_PASSWORD is missing from backend env")
    sql_file = args.backend_env.resolve().parent / "infra/mysql/migrations/20261011_ai_readonly_views.sql"
    sql = "\n".join(line for line in sql_file.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    host = ai.get("AI_DB_HOST") or backend.get("MYSQL_HOST") or "127.0.0.1"
    port = int(ai.get("AI_DB_PORT") or backend.get("MYSQL_PORT") or 3307)
    with pymysql.connect(host=host, port=port, user="root", password=root_password,
                         charset="utf8mb4", autocommit=True, connect_timeout=5, read_timeout=10) as connection:
        with connection.cursor() as cursor:
            # Never overwrite an existing reader's password or broaden an unknown account.
            cursor.execute("SELECT Host FROM mysql.user WHERE User = %s", (username,))
            existing = cursor.fetchall()
            if existing:
                if existing != (("%",),):
                    raise ValueError("Account already exists with another host; inspect it manually")
                cursor.execute("SHOW GRANTS FOR %s@'%%'", (username,))
                grants = [row[0] for row in cursor.fetchall()]
                for grant in grants:
                    if "WITH GRANT OPTION" in grant:
                        raise ValueError("Reader must not be allowed to grant access to others")
                    if grant.startswith("GRANT USAGE ON *.* TO "):
                        continue
                    match = re.match(r"GRANT SELECT ON `([^`]+)`\.`([^`]+)` TO ", grant)
                    if not match or ".".join(match.groups()) not in VIEWS:
                        raise ValueError("Existing reader has unexpected privileges; refusing to reuse it")
            for statement in sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)
            if not existing:
                cursor.execute("CREATE USER %s@'%%' IDENTIFIED BY %s", (username, password))
            for view in VIEWS:
                database, name = view.split(".")
                cursor.execute(f"GRANT SELECT ON `{database}`.`{name}` TO %s@'%%'", (username,))
    # Verify credentials and views with the actual restricted account, not root.
    with pymysql.connect(host=host, port=port, user=username, password=password,
                         charset="utf8mb4", connect_timeout=5, read_timeout=5) as connection:
        with connection.cursor() as cursor:
            for view in VIEWS:
                cursor.execute(f"SELECT * FROM {view} LIMIT 0")
            try:
                cursor.execute("SELECT id FROM identity_db.users LIMIT 0")
            except pymysql.MySQLError as error:
                if error.args[0] not in (1142, 1044):
                    raise
            else:
                raise ValueError("Reader unexpectedly has access to Identity tables")
    print("Ready: 9 AI views, SELECT-only account. Business tables/data were not changed.")
    print("Set AI_DB_FALLBACK_ENABLED=true in the AI .env and restart Identity + AI.")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not dump credentials, SQL text or connection exception contents.
        print(f"Setup failed ({type(error).__name__}). Check .env credentials, account grants and migration schema.", file=sys.stderr)
        sys.exit(1)

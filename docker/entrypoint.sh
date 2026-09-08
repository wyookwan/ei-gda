#!/bin/sh
set -e

echo "===================================="
echo "      Ei-GDA Platform"
echo "===================================="

echo "Waiting for MySQL..."

python - <<'PY'
import os
import time
import pymysql

host = os.getenv("MYSQL_HOST", "mysql")
port = int(os.getenv("MYSQL_PORT", "3306"))
user = os.getenv("MYSQL_USER")
password = os.getenv("MYSQL_PASSWORD")
database = os.getenv("MYSQL_DB")

for attempt in range(30):
    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4"
        )

        connection.close()

        print("MySQL connection successful.")
        break

    except Exception as exc:
        print(
            f"MySQL not ready "
            f"({attempt + 1}/30): {exc}"
        )
        time.sleep(2)

else:
    raise RuntimeError(
        "Ei-GDA could not connect to MySQL."
    )
PY

echo "MySQL ready."

if [ "${AUTO_MIGRATE:-True}" = "True" ]; then
    echo "Applying database schema and safe migrations..."
    python /app/migrate_v14_eigda.py
fi

echo "Starting Ei-GDA..."

exec "$@"

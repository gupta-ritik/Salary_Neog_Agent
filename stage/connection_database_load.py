
import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env", override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

try:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version()")
            db_name, version = cur.fetchone()

            print("Neon connected successfully!")
            print("Database:", db_name)
            print("Version:", version.split(",")[0])

except Exception as e:
    print("Connection failed:", type(e).__name__, str(e))

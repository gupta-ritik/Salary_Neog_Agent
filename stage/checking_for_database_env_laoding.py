import os
from dotenv import load_dotenv

load_dotenv(override=True)

url = os.getenv("DATABASE_URL", "").strip()

print("Starts with psql:", url.startswith("psql "))
print("Starts with postgresql://:", url.startswith("postgresql://"))
print("Starts with postgres://:", url.startswith("postgres://"))
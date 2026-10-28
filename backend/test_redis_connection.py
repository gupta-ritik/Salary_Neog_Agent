import os
import redis

client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)

client.set("salary_agent:test", "connected", ex=60)

print(client.get("salary_agent:test"))

client.delete("salary_agent:test")

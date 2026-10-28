import json
import logging
import os
import time
import threading
import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

import complete_stage as game
from coaching_service import generate_feedback
from psycopg.types.json import Jsonb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

game.DEBUG = False
MAX_ROUNDS = game.MAX_ROUNDS

R: dict = {}
SAVED: set = set()

# Process-local performance telemetry for the demo dashboard. It resets on API restart.
PERF_LOCK = threading.Lock()
PERF = {
    "coach_generated": 0, "coach_reused": 0, "coach_generation_latency_ms_total": 0.0,
    "coach_generation_latency_ms_count": 0, "cache_hits": 0, "cache_misses": 0,
    "api_timings": {},
}

def _inc_perf(key: str, amount: int = 1) -> None:
    with PERF_LOCK:
        PERF[key] = PERF.get(key, 0) + amount

def _record_api_timing(path: str, cache_status: str, elapsed_ms: float) -> None:
    key = f"{path}|{cache_status}"
    with PERF_LOCK:
        item = PERF["api_timings"].setdefault(key, {"count": 0, "total_ms": 0.0, "min_ms": None, "max_ms": 0.0})
        item["count"] += 1
        item["total_ms"] += elapsed_ms
        item["min_ms"] = elapsed_ms if item["min_ms"] is None else min(item["min_ms"], elapsed_ms)
        item["max_ms"] = max(item["max_ms"], elapsed_ms)

GAMES_CACHE_KEY = "salary_agent:games"
STATS_CACHE_KEY = "salary_agent:stats"
GAMES_CACHE_TTL = 15
STATS_CACHE_TTL = 60

# Rate limits apply to endpoints that can create games or trigger LLM calls.
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_CREATE_GAME = int(os.getenv("RATE_LIMIT_CREATE_GAME", "5"))
RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "10"))
RATE_LIMIT_COACH = int(os.getenv("RATE_LIMIT_COACH", "5"))

# Redis executes this script atomically, avoiding INCR/EXPIRE race conditions.
RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


def cache_get(key: str):
    """Return cached JSON data, or None on a cache miss/error."""
    client = R.get("redis")
    if client is None:
        return None
    try:
        value = client.get(key)
        _inc_perf("cache_hits" if value is not None else "cache_misses")
        return json.loads(value) if value is not None else None
    except Exception:
        logger.warning("Redis cache read failed for key %s", key, exc_info=True)
        return None


def cache_set(key: str, value, ttl: int) -> None:
    """Cache JSON-serializable data with a TTL."""
    client = R.get("redis")
    if client is None:
        return
    try:
        encoded = json.dumps(jsonable_encoder(value))
        client.setex(key, ttl, encoded)
    except Exception:
        logger.warning("Redis cache write failed for key %s", key, exc_info=True)


def invalidate_cache(*keys: str) -> None:
    """Invalidate cached responses after relevant state changes."""
    client = R.get("redis")
    if client is None:
        return
    try:
        if keys:
            client.delete(*keys)
    except Exception:
        logger.warning("Redis cache invalidation failed", exc_info=True)


def enforce_rate_limit(request: Request, bucket: str, limit: int) -> None:
    """Apply a per-client fixed-window limit using Redis.

    Redis is optional in this application, so limiter failures fail open and are
    logged. In production, consider failing closed if enforcing limits is a
    security requirement. Use request.client.host; do not trust arbitrary
    X-Forwarded-For headers unless a trusted proxy is configured.
    """
    client = R.get("redis")
    if client is None:
        return

    client_ip = request.client.host if request.client else "unknown"
    key = f"salary_agent:ratelimit:{bucket}:{client_ip}"
    try:
        result = client.eval(RATE_LIMIT_LUA, 1, key, RATE_LIMIT_WINDOW_SECONDS)
        count, ttl = int(result[0]), int(result[1])
    except Exception:
        logger.warning("Redis rate-limit check failed; allowing request", exc_info=True)
        return

    if count > limit:
        retry_after = max(1, ttl)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Too many requests. Try again in {retry_after} seconds.",
                "limit": limit,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
            headers={"Retry-After": str(retry_after)},
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    pool = None
    redis_client = None
    try:
        # Redis is optional: the application can run without it.
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            redis_client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            redis_client.ping()
            R["redis"] = redis_client
            logger.info("Redis connected successfully.")
        except Exception:
            logger.warning("Redis unavailable; continuing without cache.", exc_info=True)
            if redis_client is not None:
                redis_client.close()
            redis_client = None
            R.pop("redis", None)

        # PostgreSQL remains the authoritative persistence layer.
        pool = ConnectionPool(
            conninfo=os.environ["DATABASE_URL"],
            max_size=5,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            check=ConnectionPool.check_connection,
            open=True,
        )
        saver = PostgresSaver(pool)
        saver.setup()
        with pool.connection() as conn:
            game.create_result_tables(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS game_coaching_reports (
                    game_id TEXT PRIMARY KEY REFERENCES game_results(game_id) ON DELETE CASCADE,
                    report JSONB NOT NULL,
                    model_name TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
        R["pool"] = pool
        R["graph"] = game.build_app(saver)
        logger.info("Salary Negotiation API started successfully.")
        yield
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                logger.warning("Error closing Redis client", exc_info=True)
        if pool is not None:
            pool.close()
        R.clear()
        logger.info("Database connection pool closed.")


api = FastAPI(title="Salary Negotiation Simulator API", lifespan=lifespan)
api.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

@api.middleware("http")
async def collect_request_timing(request: Request, call_next):
    started = time.perf_counter()
    request.state.cache_status = "not_applicable"
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    path = request.url.path
    if path in ("/games", "/stats") and request.method == "GET":
        _record_api_timing(path, getattr(request.state, "cache_status", "unknown"), elapsed_ms)
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


def cfg(game_id: str) -> dict:
    return {"configurable": {"thread_id": game_id}}


def run_sql(sql: str, params=None) -> list:
    with R["pool"].connection() as conn:
        return conn.execute(sql, params).fetchall()


def build_view(game_id: str, snap) -> dict:
    """Convert a LangGraph snapshot into a browser-facing response."""
    v = snap.values
    in_progress = bool(snap.next)
    view = {
        "id": game_id,
        "in_progress": in_progress,
        "status": v["status"],
        "round": min(v["round"] + 1, MAX_ROUNDS),
        "max_rounds": MAX_ROUNDS,
        "current_offer": v["current_offer"],
        "opening_offer": v["opening_offer"],
        "messages": [
            {"role": "recruiter" if m.type == "ai" else "you", "content": m.content}
            for m in v["messages"]
        ],
        "result": None,
        "strategy_analysis": None,
    }
    if in_progress:
        view["strategy_analysis"] = {
            "planned_action": v.get("planned_action"),
            "planned_offer": v.get("planned_offer"),
            "next_objective": v.get("next_objective"),
        }
    if not in_progress:
        if game_id not in SAVED:
            with R["pool"].connection() as conn:
                game.save_game_result(conn, game_id, v)
            SAVED.add(game_id)
        final_offer = v["final_offer"]
        view["result"] = {
            "final_offer": final_offer,
            "ceiling": v["budget_ceiling"],
            "personality": v["personality"],
            "left_on_table": round(v["budget_ceiling"] - final_offer, 1) if final_offer is not None else None,
            "result_score": v["result_score"],
            "coaching_report": v.get("coaching_report") or {},
            "debrief": v["debrief"],
        }
    return view


def load_game(game_id: str):
    snap = R["graph"].get_state(cfg(game_id))
    if not snap.values:
        raise HTTPException(status_code=404, detail="Game not found")
    return snap


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@api.get("/games")
def list_games(request: Request):
    cached = cache_get(GAMES_CACHE_KEY)
    if cached is not None:
        request.state.cache_status = "hit"
        logger.info("Redis cache hit: games")
        return cached
    request.state.cache_status = "miss"

    rows = run_sql(
        "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id DESC LIMIT 30"
    )
    games = []
    for row in rows:
        game_id = row["thread_id"]
        snap = R["graph"].get_state(cfg(game_id))
        if snap.values:
            games.append({
                "id": game_id,
                "in_progress": bool(snap.next),
                "status": snap.values["status"],
                "round": min(snap.values["round"] + 1, MAX_ROUNDS),
                "current_offer": snap.values["current_offer"],
            })
    cache_set(GAMES_CACHE_KEY, games, GAMES_CACHE_TTL)
    return games


@api.post("/games", status_code=201)
def create_game(request: Request):
    enforce_rate_limit(request, "create_game", RATE_LIMIT_CREATE_GAME)
    game_id = f"game-{uuid.uuid4().hex[:8]}"
    try:
        R["graph"].invoke({}, cfg(game_id))
        snap = load_game(game_id)
        response = build_view(game_id, snap)
        invalidate_cache(GAMES_CACHE_KEY, STATS_CACHE_KEY)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to create game %s", game_id)
        raise HTTPException(
            status_code=502,
            detail=f"Could not create the game ({type(exc).__name__}). Check the backend terminal for details.",
        ) from exc


@api.get("/games/{game_id}")
def get_game(game_id: str):
    # Always fetch the latest state from LangGraph.
    return build_view(game_id, load_game(game_id))




@api.post("/games/{game_id}/coach")
def coach_game(game_id: str, request: Request):
    """Generate or retrieve an evidence-based AI coaching report for a finished game."""
    enforce_rate_limit(request, "coach", RATE_LIMIT_COACH)
    snap = load_game(game_id)
    if snap.next:
        raise HTTPException(
            status_code=409,
            detail="Coaching is available after the negotiation is finished.",
        )

    existing = run_sql(
        """
        SELECT report, model_name, prompt_version, created_at
        FROM game_coaching_reports
        WHERE game_id = %s
        """,
        (game_id,),
    )
    if existing:
        _inc_perf("coach_reused")
        row = existing[0]
        return {
            "game_id": game_id,
            "cached": True,
            "report": row["report"],
            "model": row["model_name"],
            "prompt_version": row["prompt_version"],
            "created_at": row["created_at"],
        }

    generation_started = time.perf_counter()
    try:
        generated = generate_feedback(game_id=game_id, game_state=snap.values)
        generation_ms = (time.perf_counter() - generation_started) * 1000
        _inc_perf("coach_generated")
        _inc_perf("coach_generation_latency_ms_count")
        with PERF_LOCK:
            PERF["coach_generation_latency_ms_total"] += generation_ms
    except (RuntimeError, ValueError) as exc:
        logger.warning("Coach cannot process game %s: %s", game_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI coaching generation failed for game %s", game_id)
        raise HTTPException(
            status_code=502,
            detail="AI coaching could not be generated. Please try again later.",
        ) from exc

    # Unique game_id ensures only one persisted report. In a rare race, the
    # losing request returns the winner's report, though both may have called the LLM.
    with R["pool"].connection() as conn:
        inserted = conn.execute(
            """
            INSERT INTO game_coaching_reports
                (game_id, report, model_name, prompt_version)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (game_id) DO NOTHING
            RETURNING report, model_name, prompt_version, created_at
            """,
            (
                game_id,
                Jsonb(generated["report"]),
                generated["model"],
                generated["prompt_version"],
            ),
        ).fetchone()
        created = inserted is not None
        if inserted is None:
            inserted = conn.execute(
                """
                SELECT report, model_name, prompt_version, created_at
                FROM game_coaching_reports WHERE game_id = %s
                """,
                (game_id,),
            ).fetchone()

    return {
        "game_id": game_id,
        "cached": not created,
        "report": inserted["report"],
        "model": inserted["model_name"],
        "prompt_version": inserted["prompt_version"],
        "created_at": inserted["created_at"],
    }


@api.post("/games/{game_id}/messages")
def send_message(game_id: str, body: MessageIn, request: Request):
    enforce_rate_limit(request, "messages", RATE_LIMIT_MESSAGES)
    snap = load_game(game_id)
    if not snap.next:
        raise HTTPException(status_code=409, detail="This game is finished. Start a new one.")

    try:
        R["graph"].invoke(Command(resume=body.text), cfg(game_id))
    except Exception as exc:
        logger.exception("LangGraph invocation failed for game %s", game_id)
        raise HTTPException(
            status_code=502,
            detail=f"The negotiation request failed ({type(exc).__name__}). Check the backend terminal for the full traceback.",
        ) from exc

    try:
        updated_snap = load_game(game_id)
        response = build_view(game_id, updated_snap)
        # build_view may persist a completed result to PostgreSQL, so invalidate
        # both caches only after response construction/result persistence succeeds.
        invalidate_cache(GAMES_CACHE_KEY, STATS_CACHE_KEY)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to build response for game %s", game_id)
        raise HTTPException(
            status_code=500,
            detail=(
                f"The game may have progressed, but its response could not be built ({type(exc).__name__}). "
                "Reload the game before retrying."
            ),
        ) from exc


@api.get("/performance")
def performance_metrics():
    """Return lightweight in-process metrics for the performance comparison dashboard."""
    with PERF_LOCK:
        snapshot = json.loads(json.dumps(PERF))
    timings = {}
    for key, item in snapshot["api_timings"].items():
        count = item["count"]
        timings[key] = {
            "count": count,
            "avg_ms": round(item["total_ms"] / count, 2) if count else 0,
            "min_ms": round(item["min_ms"], 2) if item["min_ms"] is not None else None,
            "max_ms": round(item["max_ms"], 2),
        }
    generated = snapshot["coach_generated"]
    reused = snapshot["coach_reused"]
    latency_count = snapshot["coach_generation_latency_ms_count"]
    total_coach_requests = generated + reused
    return {
        "scope": "current backend process; counters reset when the container restarts",
        "coaching": {
            "reports_generated": generated,
            "saved_reports_reused": reused,
            "estimated_llm_calls_avoided": reused,
            "reuse_rate_percent": round((reused / total_coach_requests) * 100, 2) if total_coach_requests else 0,
            "avg_generation_latency_ms": round(snapshot["coach_generation_latency_ms_total"] / latency_count, 2) if latency_count else None,
        },
        "redis": {"cache_hits": snapshot["cache_hits"], "cache_misses": snapshot["cache_misses"]},
        "api_latency": timings,
        "interpretation": "Compare /games|hit vs /games|miss and /stats|hit vs /stats|miss. First requests populate Redis; repeat within TTL to measure hits.",
    }


@api.get("/stats")
def stats(request: Request):
    cached = cache_get(STATS_CACHE_KEY)
    if cached is not None:
        request.state.cache_status = "hit"
        logger.info("Redis cache hit: stats")
        return cached
    request.state.cache_status = "miss"

    games = run_sql("""
        SELECT game_id, status, personality, opening_offer, ceiling,
               final_offer, result_score, rounds, finished_at
        FROM game_results
        ORDER BY finished_at DESC
    """)
    by_personality = run_sql("""
        SELECT personality, COUNT(*)::int AS games,
               ROUND(AVG(result_score)::numeric, 1)::float AS avg_score
        FROM game_results
        GROUP BY personality
        ORDER BY avg_score DESC
    """)
    by_tactic = run_sql("""
        SELECT t.tactic, COUNT(DISTINCT t.game_id)::int AS games,
               ROUND(AVG(g.result_score)::numeric, 1)::float AS avg_score
        FROM game_tactics t
        JOIN game_results g USING (game_id)
        GROUP BY t.tactic
        ORDER BY avg_score DESC
    """)
    scores = [row["result_score"] for row in games if row["result_score"] is not None]
    response = {
        "summary": {
            "games": len(games),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "best_score": max(scores) if scores else 0,
        },
        "by_personality": by_personality,
        "by_tactic": by_tactic,
        "games": games,
    }
    cache_set(STATS_CACHE_KEY, response, STATS_CACHE_TTL)
    return response

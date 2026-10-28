
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

import complete_stage as game


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
game.DEBUG = False
MAX_ROUNDS = game.MAX_ROUNDS

R: dict = {}
SAVED: set = set()


# ----------------------------------------------------------------------------
# Startup / shutdown
# ----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
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

    try:
        saver = PostgresSaver(pool)
        saver.setup()

        with pool.connection() as conn:
            game.create_result_tables(conn)

        R["pool"] = pool
        R["graph"] = game.build_app(saver)

        logger.info("Salary Negotiation API started successfully.")
        yield

    finally:
        pool.close()
        R.clear()
        logger.info("Database connection pool closed.")


api = FastAPI(
    title="Salary Negotiation Simulator API",
    lifespan=lifespan,
)


# ----------------------------------------------------------------------------
# CORS
# ----------------------------------------------------------------------------
api.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
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
            {
                "role": "recruiter" if m.type == "ai" else "you",
                "content": m.content,
            }
            for m in v["messages"]
        ],
        "result": None,
        "strategy_analysis": None,
    }

    # Strategy Planner output
    if in_progress:
        view["strategy_analysis"] = {
            "planned_action": v.get("planned_action"),
            "planned_offer": v.get("planned_offer"),
            "next_objective": v.get("next_objective"),
        }

    # Completed-game results
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
            "left_on_table": (
                round(v["budget_ceiling"] - final_offer, 1)
                if final_offer is not None
                else None
            ),
            "result_score": v["result_score"],
            "coaching_report": v.get("coaching_report") or {},
            "debrief": v["debrief"],
        }

    return view


def load_game(game_id: str):
    snap = R["graph"].get_state(cfg(game_id))

    if not snap.values:
        raise HTTPException(
            status_code=404,
            detail="Game not found",
        )

    return snap


# ----------------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------------
class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
@api.get("/games")
def list_games():
    rows = run_sql(
        "SELECT DISTINCT thread_id FROM checkpoints "
        "ORDER BY thread_id DESC LIMIT 30"
    )

    games = []

    for row in rows:
        game_id = row["thread_id"]
        snap = R["graph"].get_state(cfg(game_id))

        if snap.values:
            games.append(
                {
                    "id": game_id,
                    "in_progress": bool(snap.next),
                    "status": snap.values["status"],
                    "round": min(
                        snap.values["round"] + 1,
                        MAX_ROUNDS,
                    ),
                    "current_offer": snap.values["current_offer"],
                }
            )

    return games


@api.post("/games", status_code=201)
def create_game():
    game_id = f"game-{uuid.uuid4().hex[:8]}"

    try:
        R["graph"].invoke({}, cfg(game_id))
        snap = load_game(game_id)
        return build_view(game_id, snap)

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to create game %s",
            game_id,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Could not create the game ({type(exc).__name__}). "
                "Check the backend terminal for details."
            ),
        ) from exc


@api.get("/games/{game_id}")
def get_game(game_id: str):
    return build_view(game_id, load_game(game_id))


@api.post("/games/{game_id}/messages")
def send_message(game_id: str, body: MessageIn):
    # Load the checkpoint before invoking the graph.
    snap = load_game(game_id)

    if not snap.next:
        raise HTTPException(
            status_code=409,
            detail="This game is finished. Start a new one.",
        )

    try:
        R["graph"].invoke(
            Command(resume=body.text),
            cfg(game_id),
        )

        # Build the response separately so response-building or database
        # errors can be distinguished from graph invocation errors.
    except Exception as exc:
        logger.exception(
            "LangGraph invocation failed for game %s",
            game_id,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                f"The negotiation request failed ({type(exc).__name__}). "
                "Check the backend terminal for the full traceback."
            ),
        ) from exc

    try:
        updated_snap = load_game(game_id)
        return build_view(game_id, updated_snap)

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Failed to build response for game %s",
            game_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"The game may have progressed, but its response "
                f"could not be built ({type(exc).__name__}). "
                "Reload the game before retrying."
            ),
        ) from exc


@api.get("/stats")
def stats():
    games = run_sql(
        """
        SELECT game_id, status, personality, opening_offer, ceiling,
               final_offer, result_score, rounds, finished_at
        FROM game_results
        ORDER BY finished_at DESC
        """
    )

    by_personality = run_sql(
        """
        SELECT personality, COUNT(*)::int AS games,
               ROUND(AVG(result_score)::numeric, 1)::float AS avg_score
        FROM game_results
        GROUP BY personality
        ORDER BY avg_score DESC
        """
    )

    by_tactic = run_sql(
        """
        SELECT t.tactic, COUNT(DISTINCT t.game_id)::int AS games,
               ROUND(AVG(g.result_score)::numeric, 1)::float AS avg_score
        FROM game_tactics t
        JOIN game_results g USING (game_id)
        GROUP BY t.tactic
        ORDER BY avg_score DESC
        """
    )

    scores = [
        row["result_score"]
        for row in games
        if row["result_score"] is not None
    ]

    return {
        "summary": {
            "games": len(games),
            "avg_score": (
                round(sum(scores) / len(scores), 1)
                if scores
                else 0
            ),
            "best_score": max(scores) if scores else 0,
        },
        "by_personality": by_personality,
        "by_tactic": by_tactic,
        "games": games,
    }

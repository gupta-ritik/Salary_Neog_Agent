"""
Live Neon/PostgreSQL persistence integration tests for the Salary Negotiation Agent.

These tests use the real DATABASE_URL and create a unique test thread/result row.
They do NOT call Groq: the graph is only advanced to its initial user-input interrupt.

Requirements:
    - Run from the backend directory.
    - DATABASE_URL in .env must point to your Neon PostgreSQL database.
    - complete_stage.py must be importable from this directory.

Run:
    pytest -v test_neon_persistence.py

The result-table test deletes its temporary game_results row afterward.
The LangGraph checkpoint test uses a unique thread ID and leaves its checkpoint
rows in place so the test does not depend on undocumented checkpoint table internals.
"""

import os
import uuid

os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("GROQ_MODEL", "llama-3.3-70b-versatile")

import pytest
import psycopg
from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver

import complete_stage as agent

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="Set DATABASE_URL in backend/.env to run live Neon persistence tests.",
)


def new_thread_id():
    return f"neon-persist-test-{uuid.uuid4().hex[:12]}"


def test_langgraph_checkpoint_survives_reopening_postgres_saver():
    """Start a game, close the DB/checkpointer, reopen them, and load the same thread."""
    thread_id = new_thread_id()
    config = {"configurable": {"thread_id": thread_id}}

    # First connection: create checkpoint tables and pause at user_turn.
    with psycopg.connect(DATABASE_URL) as conn:
        with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
            saver.setup()
            app = agent.build_app(saver)
            initial_result = app.invoke({}, config)
            before = app.get_state(config)

            assert before.values, "No LangGraph state was saved."
            assert before.next, "Expected the new game to pause for candidate input."
            expected = {
                "current_offer": before.values["current_offer"],
                "budget_ceiling": before.values["budget_ceiling"],
                "personality": before.values["personality"],
                "round": before.values["round"],
                "last_message": before.values["messages"][-1].content,
            }
            assert initial_result["current_offer"] == expected["current_offer"]

    # Second connection/saver instance: this simulates a backend restart.
    with psycopg.connect(DATABASE_URL):
        with PostgresSaver.from_conn_string(DATABASE_URL) as saver:
            app_after_restart = agent.build_app(saver)
            after = app_after_restart.get_state(config)

            assert after.values, "Could not reload the game after reopening the saver."
            assert after.next, "The resumed game should still be waiting for user input."
            assert after.values["current_offer"] == expected["current_offer"]
            assert after.values["budget_ceiling"] == expected["budget_ceiling"]
            assert after.values["personality"] == expected["personality"]
            assert after.values["round"] == expected["round"]
            assert after.values["messages"][-1].content == expected["last_message"]


def test_game_result_and_tactic_history_persist_in_postgres():
    """Insert/read a test result and tactics using the application's persistence helpers."""
    game_id = new_thread_id()
    test_result = {
        "status": "accepted",
        "personality": "hardliner",
        "opening_offer": 15.0,
        "budget_ceiling": 22.0,
        "final_offer": 15.0,
        "result_score": 0.0,
        "round": 1,
        "coaching_report": {"test": True},
        "tactic_log": [
            {"round": 1, "tactics": ["accepted_too_fast", "no_clear_tactic"]}
        ],
    }

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            agent.create_result_tables(conn)
            agent.save_game_result(conn, game_id, test_result)

            row = conn.execute(
                """
                SELECT status, personality, opening_offer, ceiling,
                       final_offer, result_score, rounds, coaching_report
                FROM game_results
                WHERE game_id = %s
                """,
                (game_id,),
            ).fetchone()

            assert row is not None, "No game_results row was found."
            assert row[0] == "accepted"
            assert row[1] == "hardliner"
            assert float(row[2]) == 15.0
            assert float(row[3]) == 22.0
            assert float(row[4]) == 15.0
            assert float(row[5]) == 0.0
            assert row[6] == 1
            assert row[7]["test"] is True

            tactics = conn.execute(
                """
                SELECT tactic FROM game_tactics
                WHERE game_id = %s AND round = 1
                ORDER BY tactic
                """,
                (game_id,),
            ).fetchall()
            assert {item[0] for item in tactics} == {
                "accepted_too_fast",
                "no_clear_tactic",
            }

            # Verify save_game_result's upsert path does not duplicate a game.
            agent.save_game_result(conn, game_id, test_result)
            count = conn.execute(
                "SELECT COUNT(*) FROM game_results WHERE game_id = %s",
                (game_id,),
            ).fetchone()[0]
            assert count == 1
    finally:
        # Remove only this test's result and tactic rows. The foreign key cascades
        # game_tactics deletion when the game_results row is removed.
        with psycopg.connect(DATABASE_URL) as conn:
            agent.create_result_tables(conn)
            conn.execute("DELETE FROM game_results WHERE game_id = %s", (game_id,))
            conn.commit()

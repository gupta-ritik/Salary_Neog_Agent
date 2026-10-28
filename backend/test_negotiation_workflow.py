"""
Deterministic workflow tests for the Salary Negotiation Agent.

These tests use LangGraph's in-memory checkpointer and fake model outputs.
They do not call Groq or Neon/PostgreSQL.

Place beside complete_stage.py and run:
    pytest -v test_negotiation_workflow.py
"""

import os

os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("GROQ_MODEL", "llama-3.3-70b-versatile")
os.environ.setdefault("DATABASE_URL", "")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import complete_stage as agent


class FakeStructuredLLM:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        return self.response


def fake_coaching_report():
    return agent.CoachingReport(
        anchoring_score=10,
        justification_score=10,
        non_salary_value_score=5,
        honesty_risk_score=8,
        composure_score=8,
        biggest_mistake="No major mistake in this deterministic workflow test.",
        biggest_mistake_round=None,
        tips=[
            "State your target salary clearly.",
            "Support your request with market evidence.",
            "Consider benefits alongside base salary.",
        ],
        explanation="Deterministic test coaching report.",
    )


def make_test_app(monkeypatch):
    monkeypatch.setattr(agent, "DEBUG", False)
    monkeypatch.setattr(
        agent,
        "tagger_llm",
        FakeStructuredLLM(
            agent.TacticTags(
                tactics=["accepted_too_fast"],
                candidate_ask=None,
                accepts_offer=True,
                walks_away=False,
            )
        ),
    )
    monkeypatch.setattr(
        agent, "coach_llm", FakeStructuredLLM(fake_coaching_report())
    )
    return agent.build_app(MemorySaver())


def test_acceptance_finishes_game_and_persists_final_state(monkeypatch):
    app = make_test_app(monkeypatch)
    config = {"configurable": {"thread_id": "test-acceptance"}}

    # First invocation runs the scenario and pauses at user_turn.
    first = app.invoke({}, config)
    assert first["status"] == "ongoing"
    assert app.get_state(config).next

    opening_offer = first["current_offer"]

    # Resume the same thread with a clear acceptance.
    final = app.invoke(Command(resume="I accept"), config)

    assert final["status"] == "accepted"
    assert final["final_offer"] == opening_offer
    assert final["current_offer"] == opening_offer
    assert final["result_score"] == 0.0
    assert final["coaching_report"]["tips"]
    assert len(final["coaching_report"]["tips"]) == 3

    # State should be available from the same thread after completion.
    snapshot = app.get_state(config)
    assert snapshot.values["status"] == "accepted"
    assert snapshot.values["final_offer"] == opening_offer
    assert snapshot.next == ()


def test_saved_in_progress_game_can_be_loaded_from_same_thread(monkeypatch):
    app = make_test_app(monkeypatch)
    config = {"configurable": {"thread_id": "test-resume"}}

    first = app.invoke({}, config)
    snapshot = app.get_state(config)

    assert snapshot.values["round"] == 0
    assert snapshot.values["current_offer"] == first["current_offer"]
    assert snapshot.next  # graph is paused waiting for the candidate
    assert snapshot.values["messages"][-1].content == first["messages"][-1].content

    # Reading the same thread again returns the saved snapshot.
    loaded = app.get_state({"configurable": {"thread_id": "test-resume"}})
    assert loaded.values["budget_ceiling"] == snapshot.values["budget_ceiling"]
    assert loaded.values["personality"] == snapshot.values["personality"]
    assert loaded.values["current_offer"] == snapshot.values["current_offer"]

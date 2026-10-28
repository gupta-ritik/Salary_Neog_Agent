"""
Expanded test suite for Salary Negotiation Agent.

Targets 25 deterministic tests for strategy planning, guard behavior,
scoring, acceptance/walk-away routing, and in-memory LangGraph persistence.

No Groq API or Neon/PostgreSQL calls are made by these tests.

Place beside complete_stage.py and run:
    pytest -v test_negotiation_25_cases.py
"""

import os

os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("GROQ_MODEL", "llama-3.3-70b-versatile")
os.environ.setdefault("DATABASE_URL", "")

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import complete_stage as agent


class FakeStructuredLLM:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        if self.error:
            raise self.error
        return self.response


def state(
    current=15.0,
    ceiling=22.0,
    ask=18.0,
    personality="hardliner",
    tactics=None,
    round_number=0,
):
    return {
        "messages": [],
        "round": round_number,
        "current_offer": current,
        "budget_ceiling": ceiling,
        "opening_offer": current,
        "candidate_ask": ask,
        "personality": personality,
        "latest_tactics": tactics if tactics is not None else ["no_clear_tactic"],
        "tactic_log": [],
    }


def plan(action="counter", offer=21.0):
    return agent.RecruiterPlan(
        action=action,
        planned_offer=offer,
        rationale="Test rationale",
        next_objective="Continue a measured negotiation",
    )


@pytest.fixture(autouse=True)
def quiet_debug(monkeypatch):
    monkeypatch.setattr(agent, "DEBUG", False)


# 1
def test_hardliner_weak_tactic_small_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(state(tactics=["no_clear_tactic"]))
    assert result["planned_offer"] <= 15.5


# 2
def test_hardliner_anchoring_small_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(state(tactics=["anchoring"]))
    assert result["planned_offer"] <= 15.5


# 3
def test_hardliner_bluff_small_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(state(tactics=["bluff"]))
    assert result["planned_offer"] <= 15.5


# 4
def test_hardliner_market_data_bounded_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(state(tactics=["market_data"]))
    assert 15 <= result["planned_offer"] <= 16.5


# 5
def test_hardliner_justified_ask_bounded_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(state(tactics=["justified_ask"]))
    assert 15 <= result["planned_offer"] <= 16.5


# 6
def test_friendly_can_concede_more_than_hardliner(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    hardliner = agent.strategy_planner(
        state(personality="hardliner", tactics=["justified_ask"])
    )
    friendly = agent.strategy_planner(
        state(personality="friendly", tactics=["justified_ask"])
    )
    assert friendly["planned_offer"] >= hardliner["planned_offer"]


# 7
def test_stalling_caps_early_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=21)))
    result = agent.strategy_planner(
        state(personality="stalling", tactics=["justified_ask"], round_number=0)
    )
    assert result["planned_offer"] <= 15.3


# 8
def test_offer_never_exceeds_ceiling(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=100)))
    result = agent.strategy_planner(state(current=17, ceiling=18, ask=18))
    assert result["planned_offer"] <= 18


# 9
def test_offer_never_decreases(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(offer=1)))
    result = agent.strategy_planner(state(current=16, ceiling=22, ask=19))
    assert result["planned_offer"] >= 16


# 10
def test_impossible_accept_is_changed_to_counter(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(action="accept", offer=25)))
    result = agent.strategy_planner(state(current=15, ceiling=20, ask=25))
    assert result["planned_action"] == "counter"


# 11
def test_feasible_accept_uses_candidate_ask(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(action="accept", offer=21)))
    result = agent.strategy_planner(state(current=15, ceiling=20, ask=18))
    assert result["planned_action"] == "accept"
    assert result["planned_offer"] == 18


# 12
def test_premature_walk_is_changed_to_counter(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(action="walk", offer=15)))
    result = agent.strategy_planner(state(current=15, ceiling=20, ask=18, round_number=0))
    assert result["planned_action"] == "counter"


# 13
def test_walk_allowed_at_final_round(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan(action="walk", offer=15)))
    result = agent.strategy_planner(
        state(current=15, ceiling=20, ask=18, round_number=agent.MAX_ROUNDS - 1)
    )
    assert result["planned_action"] == "walk"


# 14
def test_planner_exception_uses_fallback(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(error=RuntimeError("test failure")))
    result = agent.strategy_planner(state(tactics=["no_clear_tactic"]))
    assert result["planned_action"] == "counter"
    assert 15 <= result["planned_offer"] <= 15.5
    assert "fallback" in result["plan_rationale"].lower()


# 15
def test_counter_plan_has_concrete_objective(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(plan()))
    result = agent.strategy_planner(state())
    assert isinstance(result["next_objective"], str)
    assert result["next_objective"].strip()


def guard_state(**overrides):
    base = {
        "opening_offer": 15.0,
        "current_offer": 16.0,
        "budget_ceiling": 22.0,
        "proposed_offer": 17.0,
        "draft_reply": "Let's discuss your expectations.",
        "proposed_action": "counter",
        "candidate_ask": 18.0,
        "round": 0,
    }
    base.update(overrides)
    return base


# 16
def test_guard_clamps_proposed_offer_to_ceiling():
    result = agent.guard(guard_state(proposed_offer=30.0))
    assert result["current_offer"] <= 22.0


# 17
def test_guard_never_reduces_current_offer():
    result = agent.guard(guard_state(proposed_offer=10.0))
    assert result["current_offer"] >= 16.0


# 18
def test_guard_accepts_feasible_candidate_ask():
    result = agent.guard(guard_state(proposed_action="accept", candidate_ask=18.0))
    assert result["status"] == "deal_reached"
    assert result["final_offer"] == 18.0


# 19
def test_guard_rejects_acceptance_above_ceiling():
    result = agent.guard(guard_state(proposed_action="accept", candidate_ask=25.0))
    assert result["status"] == "ongoing"
    assert result["final_offer"] is None
    assert result["current_offer"] == 16.0


# 20
def test_guard_walk_ends_negotiation():
    result = agent.guard(guard_state(proposed_action="walk"))
    assert result["status"] == "recruiter_walked"
    assert result["final_offer"] is None


# 21
def test_guard_times_out_at_round_limit():
    result = agent.guard(
        guard_state(round=agent.MAX_ROUNDS - 1, proposed_action="counter")
    )
    assert result["status"] == "timeout"
    assert result["final_offer"] is None


# 22
def test_score_at_opening_is_zero():
    result = agent.compute_result_score(
        {"status": "deal_reached", "final_offer": 15, "opening_offer": 15, "budget_ceiling": 22}
    )
    assert result == 0.0


# 23
def test_score_at_ceiling_is_forty():
    result = agent.compute_result_score(
        {"status": "accepted", "final_offer": 22, "opening_offer": 15, "budget_ceiling": 22}
    )
    assert result == 40.0


# 24
def test_no_deal_has_zero_result_score():
    result = agent.compute_result_score(
        {"status": "timeout", "final_offer": None, "opening_offer": 15, "budget_ceiling": 22}
    )
    assert result == 0.0


# 25
def test_memory_checkpointer_preserves_paused_game(monkeypatch):
    monkeypatch.setattr(agent, "DEBUG", False)
    app = agent.build_app(MemorySaver())
    config = {"configurable": {"thread_id": "test-thread-25"}}
    first = app.invoke({}, config)
    snapshot = app.get_state(config)

    assert snapshot.next
    assert snapshot.values["current_offer"] == first["current_offer"]
    assert snapshot.values["budget_ceiling"] == first["budget_ceiling"]
    assert snapshot.values["personality"] == first["personality"]
    assert snapshot.values["messages"][-1].content == first["messages"][-1].content

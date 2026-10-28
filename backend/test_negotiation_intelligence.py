"""
Unit tests for the Salary Negotiation Agent's strategy planner and scoring.

Usage:
    1. Put this file beside complete_stage.py.
    2. Install pytest if needed: pip install pytest
    3. Run: pytest -q test_negotiation_intelligence.py

The tests mock the planner LLM, so they do not make Groq API calls.
They import complete_stage.py, so its Python dependencies must be installed.
"""

import os
from types import SimpleNamespace

# complete_stage.py validates these variables during import.
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("GROQ_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("DATABASE_URL", "")

import pytest
import complete_stage as agent


class FakeStructuredLLM:
    """Minimal fake for llm.with_structured_output(...).invoke(...)."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _messages):
        if self.error:
            raise self.error
        return self.response


def make_state(
    *,
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
        "latest_tactics": tactics or ["no_clear_tactic"],
        "tactic_log": [],
    }


def fake_plan(action="counter", offer=21.0):
    return agent.RecruiterPlan(
        action=action,
        planned_offer=offer,
        rationale="Test rationale",
        next_objective="Continue a measured negotiation",
    )


@pytest.fixture(autouse=True)
def disable_debug(monkeypatch):
    monkeypatch.setattr(agent, "DEBUG", False)


def test_counter_offer_never_exceeds_ceiling(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(offer=100.0)))
    result = agent.strategy_planner(make_state(current=15, ceiling=18, ask=17))
    assert result["planned_action"] == "counter"
    assert 15 <= result["planned_offer"] <= 18


def test_counter_offer_respects_hardliner_concession_cap(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(offer=21.0)))
    result = agent.strategy_planner(
        make_state(current=15.0, ceiling=25.0, ask=20.0,
                   personality="hardliner", tactics=["no_clear_tactic"])
    )
    assert result["planned_offer"] <= 15.5


def test_strong_evidence_allows_but_bounds_larger_concession(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(offer=21.0)))
    result = agent.strategy_planner(
        make_state(current=15.0, ceiling=25.0, ask=20.0,
                   personality="hardliner", tactics=["market_data"])
    )
    assert 15.0 <= result["planned_offer"] <= 16.5


def test_stalling_personality_moves_only_a_little_before_final_round(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(offer=21.0)))
    result = agent.strategy_planner(
        make_state(current=15.0, ceiling=25.0, ask=20.0,
                   personality="stalling", tactics=["justified_ask"], round_number=0)
    )
    assert result["planned_offer"] <= 15.3


def test_impossible_accept_is_changed_to_counter(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(action="accept", offer=30)))
    result = agent.strategy_planner(make_state(current=15, ceiling=20, ask=25))
    assert result["planned_action"] == "counter"
    assert result["planned_offer"] <= 20


def test_premature_walk_with_feasible_ask_is_changed_to_counter(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(fake_plan(action="walk", offer=15)))
    result = agent.strategy_planner(make_state(current=15, ceiling=20, ask=18, round_number=0))
    assert result["planned_action"] == "counter"


def test_planner_failure_uses_safe_fallback(monkeypatch):
    monkeypatch.setattr(agent, "llm", FakeStructuredLLM(error=RuntimeError("simulated failure")))
    result = agent.strategy_planner(
        make_state(current=15, ceiling=20, ask=18, personality="hardliner",
                   tactics=["no_clear_tactic"])
    )
    assert result["planned_action"] == "counter"
    assert 15 <= result["planned_offer"] <= 15.5
    assert "fallback" in result["plan_rationale"].lower()


@pytest.mark.parametrize(
    ("final_offer", "expected"),
    [
        (15.0, 0.0),   # no improvement over opening
        (18.5, 20.0),  # halfway from 15 to 22, rounded to one decimal
        (22.0, 40.0),  # ceiling reached
    ],
)
def test_result_score_for_valid_deal(final_offer, expected):
    state = {
        "status": "deal_reached",
        "final_offer": final_offer,
        "opening_offer": 15.0,
        "budget_ceiling": 22.0,
    }
    assert agent.compute_result_score(state) == expected


@pytest.mark.parametrize("status", ["ongoing", "timeout", "recruiter_walked", "walked_away"])
def test_no_deal_has_zero_result_score(status):
    state = {
        "status": status,
        "final_offer": None,
        "opening_offer": 15.0,
        "budget_ceiling": 22.0,
    }
    assert agent.compute_result_score(state) == 0.0


@pytest.mark.parametrize(
    ("final_offer", "opening", "ceiling"),
    [
        (14.0, 15.0, 22.0),  # below opening
        (23.0, 15.0, 22.0),  # above ceiling
        (10.0, 15.0, 9.0),   # invalid opening/ceiling relationship
    ],
)
def test_invalid_deal_values_raise(final_offer, opening, ceiling):
    state = {
        "status": "accepted",
        "final_offer": final_offer,
        "opening_offer": opening,
        "budget_ceiling": ceiling,
    }
    with pytest.raises(ValueError):
        agent.compute_result_score(state)

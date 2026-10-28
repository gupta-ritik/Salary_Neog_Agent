import pytest
from pydantic import ValidationError

from coaching_service import (
    CoachingFeedback,
    EvidenceItem,
    TacticScore,
    generate_feedback,
)


def sample_feedback():
    return CoachingFeedback(
        overall_assessment="You supported your ask but could anchor earlier.",
        strengths=[
            EvidenceItem(
                observation="You justified your salary request.",
                evidence="Candidate: Based on my experience, I am targeting 20 LPA.",
                recommendation="Keep linking asks to role-relevant evidence.",
            )
        ],
        improvements=[],
        missed_opportunities=["You did not explore a joining bonus."],
        tactic_scores=[
            TacticScore(
                tactic="justified_ask",
                score=4,
                rationale="The candidate gave a reason for the ask.",
            )
        ],
        suggested_responses=[
            {
                "situation": "When the recruiter says the budget is fixed",
                "response": "Could we explore a joining bonus or an early compensation review?",
            }
        ],
        next_time_plan=["Prepare a target range and walk-away point."],
        confidence="medium",
        limitations="Only the recorded conversation was evaluated.",
    )


class FakeStructuredLLM:
    def with_structured_output(self, schema):
        assert schema is CoachingFeedback
        return self

    def invoke(self, messages):
        assert "Transcript:" in messages[1].content
        return sample_feedback()


def test_report_schema_accepts_valid_structured_feedback():
    report = sample_feedback()
    assert report.tactic_scores[0].score == 4
    assert report.confidence == "medium"


def test_tactic_score_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        TacticScore(
            tactic="anchoring",
            score=8,
            rationale="Invalid score should fail.",
        )


def test_generate_feedback_uses_structured_output(monkeypatch):
    import coaching_service

    monkeypatch.setattr(coaching_service, "_llm", lambda: FakeStructuredLLM())
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    from langchain_core.messages import HumanMessage, AIMessage

    state = {
        "status": "accepted",
        "opening_offer": 16.0,
        "final_offer": 19.0,
        "round": 3,
        "result_score": 28.0,
        "budget_ceiling": 25.0,  # must not be placed into model context
        "messages": [
            AIMessage(content="We can offer 16 LPA."),
            HumanMessage(content="Based on my experience, I am targeting 20 LPA."),
        ],
    }
    result = generate_feedback(game_id="game-test", game_state=state)
    assert result["model"] == "test-model"
    assert result["prompt_version"] == "coach-v1"
    assert result["report"]["tactic_scores"][0]["score"] == 4


def test_generate_feedback_rejects_empty_transcript(monkeypatch):
    import coaching_service

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    with pytest.raises(ValueError, match="transcript"):
        generate_feedback(game_id="game-empty", game_state={"messages": []})

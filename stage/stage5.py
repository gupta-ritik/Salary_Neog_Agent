
import os
import random
import operator
from typing import Annotated, Literal, Optional, TypedDict

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages


# ============================================================
# 1. CONFIGURATION
# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL")

if not GROQ_API_KEY or not MODEL:
    raise ValueError(
        "Set GROQ_API_KEY and GROQ_MODEL in your .env file."
    )

llm = ChatGroq(
    model=MODEL,
    api_key=GROQ_API_KEY,
    temperature=0.7,
)

tagger_llm = ChatGroq(
    model=MODEL,
    api_key=GROQ_API_KEY,
    temperature=0,
)

coach_llm = ChatGroq(
    model=MODEL,
    api_key=GROQ_API_KEY,
    temperature=0.3,
)

MAX_ROUNDS = 4
DEBUG = True


# ============================================================
# 2. PERSONALITIES AND TACTIC REACTIONS
# ============================================================

PERSONALITIES = {
    "hardliner": (
        "Firm and brief. Concede only small steps "
        "and only for strong justification."
    ),
    "friendly": (
        "Warm and chatty. Concede more readily, "
        "but ask for something in return."
    ),
    "stalling": (
        "Evasive. Say you must check with your manager. "
        "Concede only after repeated pressure."
    ),
}

TACTIC_REACTIONS = {
    "anchoring": (
        "The candidate named a high number first. "
        "Counter, but do not move far."
    ),
    "justified_ask": (
        "The ask has a reason. Reward it with a decent concession."
    ),
    "market_data": (
        "They cite market data. Take it seriously, but ask for proof."
    ),
    "competing_offer": (
        "They claim another offer. Take it seriously, "
        "but remember it is unverified."
    ),
    "bluff": "This sounds like a bluff. Do not concede.",
    "emotional_appeal": (
        "Be polite and sympathetic, but give a small or no concession."
    ),
    "asked_non_salary_perks": (
        "Consider bonuses, remote days, or a compensation review."
    ),
    "accepted_too_fast": (
        "They accepted immediately. Do not add anything."
    ),
    "no_clear_tactic": "No clear argument. Give no concession.",
}

Tactic = Literal[
    "anchoring",
    "justified_ask",
    "market_data",
    "competing_offer",
    "bluff",
    "emotional_appeal",
    "asked_non_salary_perks",
    "accepted_too_fast",
    "no_clear_tactic",
]

Status = Literal[
    "ongoing",
    "accepted",
    "deal_reached",
    "walked_away",
    "recruiter_walked",
    "timeout",
]


# ============================================================
# 3. STRUCTURED OUTPUT SCHEMAS
# ============================================================

class TacticTags(BaseModel):
    tactics: list[Tactic] = Field(
        description="Tactics used in the candidate's latest message."
    )

    candidate_ask: Optional[float] = Field(
        default=None,
        description=(
            "Salary requested by the candidate in LPA. "
            "Use null if no specific salary target is stated."
        ),
    )

    accepts_offer: bool = Field(
        default=False,
        description=(
            "True only if the candidate clearly accepts "
            "the current recruiter offer."
        ),
    )

    walks_away: bool = Field(
        default=False,
        description=(
            "True only if the candidate clearly ends "
            "the negotiation without accepting."
        ),
    )


class RecruiterMove(BaseModel):
    reply: str = Field(
        description="The recruiter's message to the candidate."
    )

    new_offer: float = Field(
        ge=0,
        description="Proposed salary in LPA."
    )

    action: Literal["counter", "accept", "walk"] = Field(
        description=(
            "counter = continue negotiating; "
            "accept = accept the candidate's salary request; "
            "walk = end negotiations."
        ),
    )


# ============================================================
# 4. LANGGRAPH STATE
# ============================================================

class State(TypedDict):
    messages: Annotated[list, add_messages]

    round: int
    current_offer: float
    opening_offer: float
    budget_ceiling: float
    personality: str

    quit: bool
    status: Status
    final_offer: Optional[float]

    tactic_log: Annotated[list, operator.add]
    latest_tactics: list
    candidate_ask: Optional[float]
    user_accepts: bool
    user_walks: bool

    draft_reply: str
    proposed_offer: float
    proposed_action: str

    result_score: float
    debrief: str


# ============================================================
# 5. SCENARIO NODE
# ============================================================

def scenario(state: State) -> dict:
    ceiling = random.randint(14, 30)

    opening = round(
        ceiling * random.uniform(0.70, 0.82), 1
    )

    personality = random.choice(list(PERSONALITIES))

    greeting = (
        f"Hi! We'd like to offer you {opening} LPA. "
        "What do you think?"
    )

    print(f"\nRecruiter: {greeting}")

    return {
        "budget_ceiling": ceiling,
        "opening_offer": opening,
        "current_offer": opening,
        "personality": personality,
        "round": 0,
        "quit": False,
        "status": "ongoing",
        "final_offer": None,
        "messages": [AIMessage(content=greeting)],
        "tactic_log": [],
        "latest_tactics": [],
        "candidate_ask": None,
        "user_accepts": False,
        "user_walks": False,
        "draft_reply": "",
        "proposed_offer": opening,
        "proposed_action": "counter",
        "result_score": 0.0,
        "debrief": "",
    }


# ============================================================
# 6. USER TURN NODE
# ============================================================

def user_turn(state: State) -> dict:
    text = input(
        f"\n[Round {state['round'] + 1}/{MAX_ROUNDS} | "
        f"Offer: {state['current_offer']} LPA] You: "
    ).strip()

    return {
        "messages": [HumanMessage(content=text)],
        "quit": text.lower() == "quit",
    }


# ============================================================
# 7. TACTIC ANALYZER NODE
# ============================================================

def tactic_analyzer(state: State) -> dict:
    last_user_text = state["messages"][-1].content

    system = SystemMessage(
        content=(
            "Analyze the candidate's latest salary negotiation message. "
            "Use only the allowed tactic labels. "
            f"The current offer is {state['current_offer']} LPA. "
            "Extract candidate_ask only when the candidate states "
            "a salary they personally want, not merely another offer. "
            "A claim about another job offer is competing_offer. "
            "A counteroffer is not acceptance. "
            "Accept only when the candidate clearly agrees to "
            "the current recruiter offer. "
            "Walk away only when the candidate clearly ends "
            "the negotiation. If intent is ambiguous, use false."
        )
    )

    try:
        analyzer = tagger_llm.with_structured_output(TacticTags)

        result = analyzer.invoke([
            system,
            HumanMessage(content=last_user_text),
        ])

    except Exception as exc:
        print(
            f"\nAnalyzer error: {type(exc).__name__}. "
            "Using safe fallback."
        )

        result = TacticTags(
            tactics=["no_clear_tactic"],
            candidate_ask=None,
            accepts_offer=False,
            walks_away=False,
        )

    if not result.tactics:
        result.tactics = ["no_clear_tactic"]

    if DEBUG:
        print("\n[TACTIC ANALYSIS]")
        print(result.model_dump_json(indent=2))

    return {
        "tactic_log": [
            {
                "round": state["round"] + 1,
                "tactics": result.tactics,
                "candidate_ask": result.candidate_ask,
            }
        ],
        "latest_tactics": result.tactics,
        "candidate_ask": result.candidate_ask,
        "user_accepts": result.accepts_offer,
        "user_walks": result.walks_away,
    }


# ============================================================
# 8. FINALIZE CANDIDATE DECISION
# ============================================================

def finalize(state: State) -> dict:
    if state["user_accepts"] and not state["quit"]:
        return {
            "status": "accepted",
            "final_offer": state["current_offer"],
        }

    return {
        "status": "walked_away",
        "final_offer": None,
    }


# ============================================================
# 9. RECRUITER NODE — JSON STRUCTURED OUTPUT
# ============================================================

def recruiter(state: State) -> dict:
    reactions = "\n".join(
        f"- {TACTIC_REACTIONS[t]}"
        for t in state["latest_tactics"]
    )

    system = SystemMessage(
        content=(
            "You are a professional recruiter negotiating "
            "a software engineer's salary.\n"
            f"Private maximum budget: {state['budget_ceiling']} LPA. "
            "Never disclose the budget ceiling.\n"
            f"Personality: {state['personality']}. "
            f"{PERSONALITIES[state['personality']]}\n"
            f"Current offer: {state['current_offer']} LPA.\n"
            f"Candidate's requested salary: "
            f"{state['candidate_ask']} LPA.\n"
            f"React to the candidate's tactics:\n{reactions}\n\n"
            "Choose one action: counter, accept, or walk.\n"
            "Accept only if a specific candidate salary request "
            "is affordable and at least the current offer.\n"
            "Never propose a salary below the current offer "
            "or above the budget ceiling.\n"
            "Keep the reply under 60 words."
        )
    )

    recruiter_llm = llm.with_structured_output(RecruiterMove)

    move = recruiter_llm.invoke([
        system,
        *state["messages"],
    ])

    if DEBUG:
        print("\n[RECRUITER JSON]")
        print(move.model_dump_json(indent=2))

    return {
        "draft_reply": move.reply,
        "proposed_offer": move.new_offer,
        "proposed_action": move.action,
    }


# ============================================================
# 10. GUARD NODE — VALIDATE RECRUITER DECISION
# ============================================================

def guard(state: State) -> dict:
    ceiling = state["budget_ceiling"]
    current = state["current_offer"]
    ask = state["candidate_ask"]

    proposed = state["proposed_offer"]
    action = state["proposed_action"]
    reply = state["draft_reply"]

    # Clamp salary to the permitted range.
    offer = round(
        max(current, min(proposed, ceiling)), 1
    )

    was_clamped = offer != round(proposed, 1)

    # Basic disclosure check, not a comprehensive leak detector.
    leaked = (
        str(int(ceiling)) in reply
        and offer != ceiling
    )

    status = "ongoing"
    final_offer = None
    invalid_acceptance = False

    if action == "accept":
        if ask is not None and current <= ask <= ceiling:
            offer = round(ask, 1)
            status = "deal_reached"
            final_offer = offer
        else:
            invalid_acceptance = True

    elif action == "walk":
        status = "recruiter_walked"

    # Align the reply with the validated action.
    if status == "deal_reached":
        reply = (
            f"Deal! We're happy to offer you {offer} LPA. "
            "Welcome aboard."
        )

    elif status == "recruiter_walked":
        if leaked:
            reply = (
                "I'm sorry, we cannot meet your expectations, "
                "so we'll end the discussion here."
            )

    elif invalid_acceptance:
        reply = (
            f"I cannot agree to that request at this stage. "
            f"My current offer is {current} LPA. "
            "Let's continue discussing compensation."
        )

    elif was_clamped or leaked:
        reply = f"I can offer {offer} LPA. Let's continue our discussion."

    # Advance the recruiter-response counter.
    new_round = state["round"] + 1

    if status == "ongoing" and new_round >= MAX_ROUNDS:
        status = "timeout"

    print(f"\nRecruiter: {reply}")

    return {
        "messages": [AIMessage(content=reply)],
        "current_offer": offer,
        "round": new_round,
        "status": status,
        "final_offer": final_offer,
    }


# ============================================================
# 11. RESULT SCORING
# ============================================================

def compute_result_score(state: State) -> float:
    final_offer = state["final_offer"]

    if final_offer is None:
        return 0.0

    opening = state["opening_offer"]
    ceiling = state["budget_ceiling"]

    room = ceiling - opening

    if room <= 0:
        return 0.0

    captured = final_offer - opening
    score = 40 * captured / room

    return round(max(0.0, min(40.0, score)), 1)


# ============================================================
# 12. COACH NODE
# ============================================================

def coach(state: State) -> dict:
    result_score = compute_result_score(state)

    transcript = "\n".join(
        f"{'Recruiter' if m.type == 'ai' else 'Candidate'}: "
        f"{m.content}"
        for m in state["messages"]
    )

    if state["final_offer"] is not None:
        money_left = round(
            state["budget_ceiling"] - state["final_offer"], 1
        )
        money_text = (
            f"{money_left} LPA below the budget ceiling. "
            "This is theoretical remaining negotiation room, "
            "not a guaranteed obtainable salary."
        )
    else:
        money_text = (
            "No deal was reached; there is no accepted salary "
            "to compare against the ceiling."
        )

    prompt = f"""
You are a professional salary negotiation coach.

Treat the following values as authoritative:
Outcome: {state['status']}
Final offer: {state['final_offer']} LPA
Opening offer: {state['opening_offer']} LPA
Budget ceiling: {state['budget_ceiling']} LPA
Recruiter personality: {state['personality']}
Result score: {result_score}/40
Money left on the table: {money_text}
Tactic history: {state['tactic_log']}

Transcript:
{transcript}

Evaluate the candidate using this 100-point rubric:
- Result: {result_score}/40. Use this exact score.
- Anchoring: /15.
- Justification: /15.
- Non-salary value: /10.
- Honesty/risk: /10.
- Composure: /10.

Provide:
1. Each category score and reason.
2. Total score out of 100.
3. Money left on the table, using the supplied facts.
4. Biggest mistake and its round, if identifiable.
5. Three concrete tips for the next negotiation.

Do not invent events or offers. Be concise and constructive.
"""

    response = coach_llm.invoke([
        SystemMessage(content=prompt),
        HumanMessage(content="Generate the final coaching report."),
    ])

    return {
        "result_score": result_score,
        "debrief": response.content,
    }


# ============================================================
# 13. ROUTING FUNCTIONS
# ============================================================

def after_user(state: State) -> str:
    if state["quit"]:
        return "finalize"

    return "tactic_analyzer"


def after_analyzer(state: State) -> str:
    if state["user_accepts"] or state["user_walks"]:
        return "finalize"

    return "recruiter"


def after_guard(state: State) -> str:
    if state["status"] != "ongoing":
        return "coach"

    return "user_turn"


# ============================================================
# 14. BUILD THE LANGGRAPH
# ============================================================

def build_app():
    graph = StateGraph(State)

    graph.add_node("scenario", scenario)
    graph.add_node("user_turn", user_turn)
    graph.add_node("tactic_analyzer", tactic_analyzer)
    graph.add_node("finalize", finalize)
    graph.add_node("recruiter", recruiter)
    graph.add_node("guard", guard)
    graph.add_node("coach", coach)

    graph.add_edge(START, "scenario")
    graph.add_edge("scenario", "user_turn")

    graph.add_conditional_edges(
        "user_turn",
        after_user,
        {
            "finalize": "finalize",
            "tactic_analyzer": "tactic_analyzer",
        },
    )

    graph.add_conditional_edges(
        "tactic_analyzer",
        after_analyzer,
        {
            "finalize": "finalize",
            "recruiter": "recruiter",
        },
    )

    graph.add_edge("recruiter", "guard")

    graph.add_conditional_edges(
        "guard",
        after_guard,
        {
            "coach": "coach",
            "user_turn": "user_turn",
        },
    )

    graph.add_edge("finalize", "coach")
    graph.add_edge("coach", END)

    return graph.compile()


# ============================================================
# 15. MAIN ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app = build_app()

    try:
        result = app.invoke({})

        print("\n" + "=" * 55)
        print(f"RESULT: {result['status'].upper()}")
        print(f"Final offer: {result['final_offer']} LPA")
        print(f"Opening offer: {result['opening_offer']} LPA")
        print(f"Personality: {result['personality']}")
        print(f"Budget ceiling: {result['budget_ceiling']} LPA")
        print(f"Result score: {result['result_score']}/40")
        print("=" * 55)

        print("\nCOACHING REPORT\n")
        print(result["debrief"])

    except KeyboardInterrupt:
        print("\nNegotiation interrupted.")

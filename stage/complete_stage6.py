import operator

import os

import random

from typing import Annotated, Literal, Optional, TypedDict

import psycopg

from dotenv import load_dotenv

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from langchain_groq import ChatGroq

from langgraph.checkpoint.postgres import PostgresSaver

from langgraph.graph import END, START, StateGraph

from langgraph.graph.message import add_messages

from langgraph.types import Command, interrupt

from psycopg.types.json import Jsonb

from pydantic import BaseModel, Field

# ============================================================

# 1. CONFIGURATION

# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL = os.getenv("GROQ_MODEL")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not GROQ_API_KEY or not MODEL:

    raise ValueError("Set GROQ_API_KEY and GROQ_MODEL in your .env file.")

llm = ChatGroq(model=MODEL, api_key=GROQ_API_KEY, temperature=0.7)

tagger_llm = ChatGroq(model=MODEL, api_key=GROQ_API_KEY, temperature=0)

coach_llm = ChatGroq(model=MODEL, api_key=GROQ_API_KEY, temperature=0.3)

MAX_ROUNDS = 4

DEBUG = True  # prints the tags each round. Set False for the real game.

PERSONALITIES = {

    "hardliner": "Firm and brief. Concede only small steps, and only for strong justification.",

    "friendly": "Warm and chatty. Concede more readily, but ask for something in return.",

    "stalling": "Evasive. Say you must check with your manager. Concede only after repeated pressure.",

}

TACTIC_REACTIONS = {

    "anchoring": "The candidate named a high number first. Counter, but do not move far.",

    "justified_ask": "The ask has a reason. Reward it with a decent concession.",

    "market_data": "They cite market data. Take it seriously, but ask for proof.",

    "competing_offer": "They claim another offer. Be a little worried, but you cannot verify it.",

    "bluff": "This sounds like a bluff. Do not concede.",

    "emotional_appeal": "Be polite and sympathetic, but give a very small or no concession.",

    "asked_non_salary_perks": "Offer perks (bonus, remote days, review) instead of base salary.",

    "accepted_too_fast": "They accepted immediately. Do not add anything.",

    "no_clear_tactic": "No clear argument. Give no concession.",

}

# Plain-code acceptance check: some messages are so clear that no LLM is needed.

ACCEPT_WORDS = {"accept", "i accept", "accepted", "deal", "i accept the offer", "i accept your offer"}

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

Status = Literal["ongoing", "accepted", "deal_reached", "walked_away", "recruiter_walked", "timeout"]

# --- Structured outputs ------------------------------------------------------

class TacticTags(BaseModel):

    tactics: list[Tactic] = Field(description="Every tactic used in the candidate's latest message")

    candidate_ask: Optional[float] = Field(default=None, description="Salary in LPA the candidate asks for")

    accepts_offer: bool = Field(

        default=False, description="True only if the candidate clearly accepts the recruiter's CURRENT offer"

    )

    walks_away: bool = Field(

        default=False, description="True only if the candidate clearly ends the negotiation"

    )

class RecruiterMove(BaseModel):

    reply: str = Field(description="What the recruiter says. Never mention the budget ceiling.")

    new_offer: float = Field(description="The recruiter's offer in LPA after this reply")

    action: Literal["counter", "accept", "walk"] = Field(

        description="counter = keep negotiating; accept = agree to the candidate's ask; walk = end talks"

    )

class CoachingReport(BaseModel):

    """Validated structure for the coaching model's evaluation."""

    anchoring_score: int = Field(ge=0, le=15, description="Anchoring score out of 15")

    justification_score: int = Field(ge=0, le=15, description="Justification score out of 15")

    non_salary_value_score: int = Field(ge=0, le=10, description="Non-salary value score out of 10")

    honesty_risk_score: int = Field(ge=0, le=10, description="Honesty and risk score out of 10")

    composure_score: int = Field(ge=0, le=10, description="Composure score out of 10")

    biggest_mistake: str = Field(description="Candidate's biggest mistake")

    biggest_mistake_round: Optional[int] = Field(default=None, description="Round where the mistake occurred, if known")

    tips: list[str] = Field(min_length=3, max_length=3, description="Exactly three concrete tips for next time")

    explanation: str = Field(description="Concise plain-language explanation of the evaluation")

# --- State -----------------------------------------------------------------

class State(TypedDict):

    messages: Annotated[list, add_messages]

    round: int

    current_offer: float

    quit: bool

    status: Status

    final_offer: Optional[float]

    budget_ceiling: float

    personality: str

    opening_offer: float

    tactic_log: list

    latest_tactics: list

    candidate_ask: Optional[float]

    user_accepts: bool

    user_walks: bool

    draft_reply: str

    proposed_offer: float

    proposed_action: str

    result_score: float

    debrief: str

    coaching_report: dict  # FIX: this key was missing, so LangGraph silently dropped it

# --- Nodes (no print() calls except DEBUG: the loop at the bottom does the printing) ----

def scenario(state: State) -> dict:

    ceiling = random.randint(14, 30)

    opening = round(ceiling * random.uniform(0.70, 0.82), 1)

    personality = random.choice(list(PERSONALITIES))

    greeting = AIMessage(content=f"Hi! We'd like to offer you {opening} LPA. What do you think?")

    return {

        "budget_ceiling": ceiling,

        "personality": personality,

        "opening_offer": opening,

        "current_offer": opening,

        "round": 0,

        "quit": False,

        "status": "ongoing",

        "final_offer": None,

        "messages": [greeting],

        "tactic_log": [],

        "latest_tactics": [],

        "candidate_ask": None,

        "user_accepts": False,

        "user_walks": False,

        "result_score": 0.0,

        "debrief": "",

        "coaching_report": {},

    }

def user_turn(state: State) -> dict:

    # interrupt() PAUSES the graph here. When the loop calls

    # app.invoke(Command(resume=text), config), this node restarts and

    # interrupt() returns that text. Keep it as the FIRST line of the node:

    # on resume the node runs again from the top.

    text = interrupt({"round": state["round"] + 1, "current_offer": state["current_offer"]})

    text = text.strip()

    return {"messages": [HumanMessage(content=text)], "quit": text.lower() == "quit"}

def tactic_analyzer(state: State) -> dict:

    last_user_text = state["messages"][-1].content

    analyzer = tagger_llm.with_structured_output(TacticTags)

    system = SystemMessage(

        content=(

            "You label salary-negotiation tactics used by a candidate. "

            f"The recruiter's current offer is {state['current_offer']} LPA. "

            "Use only tactics from the allowed list. "

            "A claim of another offer is 'competing_offer'. "

            "Set candidate_ask only if the candidate states a salary number they want. "

            "Set accepts_offer=true ONLY if the candidate clearly agrees to the current offer "

            "(then also use 'accepted_too_fast' if it is the first round). "

            "Set walks_away=true ONLY if the candidate clearly ends the negotiation."

        )

    )

    try:

        result = analyzer.invoke([system, HumanMessage(content=last_user_text)])

    except Exception:

        result = TacticTags(tactics=["no_clear_tactic"])

    if not result.tactics:

        result.tactics = ["no_clear_tactic"]

    # Code backs up the LLM for unmistakable acceptances.

    accepts = result.accepts_offer or last_user_text.lower().strip(" .!") in ACCEPT_WORDS

    if DEBUG:

        print(f"   [DEBUG tags: {result.tactics} | ask: {result.candidate_ask} | accepts: {accepts}]")

    return {

        "tactic_log": [

            *state.get("tactic_log", []),

            {"round": state["round"] + 1, "tactics": result.tactics},

        ],

        "latest_tactics": result.tactics,

        "candidate_ask": result.candidate_ask,

        "user_accepts": accepts,

        "user_walks": result.walks_away,

    }

def finalize(state: State) -> dict:

    if state["user_accepts"]:

        return {"status": "accepted", "final_offer": state["current_offer"]}

    return {"status": "walked_away", "final_offer": None}

def recruiter(state: State) -> dict:

    reactions = "\n".join(f"- {TACTIC_REACTIONS[t]}" for t in state["latest_tactics"])

    system = SystemMessage(

        content=(

            "You are a recruiter negotiating a software engineer's salary.\n"

            f"PRIVATE max budget: {state['budget_ceiling']} LPA. Never reveal or hint at it.\n"

            f"Personality: {state['personality']} -> {PERSONALITIES[state['personality']]}\n"

            f"Your current offer is {state['current_offer']} LPA. Never lower it.\n"

            f"The candidate asked for: {state['candidate_ask']} LPA.\n"

            f"How to react to this candidate's tactics:\n{reactions}\n"

            "Choose an action:\n"

            "- 'counter': keep negotiating (the default)\n"

            "- 'accept': ONLY if the candidate's ask is reasonable and within your budget\n"

            "- 'walk': ONLY if the candidate is unreasonable or keeps bluffing\n"

            "Keep the reply under 60 words."

        )

    )

    mover = llm.with_structured_output(RecruiterMove)

    move = mover.invoke([system, *state["messages"]])

    return {

        "draft_reply": move.reply,

        "proposed_offer": move.new_offer,

        "proposed_action": move.action,

    }

def guard(state: State) -> dict:
    """Validate recruiter action and offer before committing graph state."""
    ceiling = float(state["budget_ceiling"])
    current = float(state["current_offer"])
    proposed = float(state["proposed_offer"])
    reply = state["draft_reply"].strip()
    action = state["proposed_action"]
    ask = state.get("candidate_ask")

    if not (0 < state["opening_offer"] <= current <= ceiling):
        raise ValueError(
            "Invalid negotiation state: expected 0 < opening_offer <= current_offer <= budget_ceiling."
        )
    if action not in {"counter", "accept", "walk"}:
        action = "counter"

    offer = round(max(current, min(proposed, ceiling)), 1)
    proposed_was_clamped = offer != round(proposed, 1)
    status: Status = "ongoing"
    final: Optional[float] = None

    if action == "accept":
        if ask is not None and current <= float(ask) <= ceiling:
            offer = round(float(ask), 1)
            final = offer
            status = "deal_reached"
            reply = f"Deal! We're happy to offer you {offer:.1f} LPA. Welcome aboard."
        else:
            action = "counter"
            offer = current
            reply = f"I can't agree to that request as stated. Our current offer remains {offer:.1f} LPA."

    elif action == "walk":
        offer = current
        status = "recruiter_walked"
        final = None
        reply = "I'm sorry, we can't reach an agreement, so we'll end the discussion here."

    else:
        ceiling_tokens = {str(int(ceiling)), f"{ceiling:.1f}", f"{ceiling:g}"}
        leaked = any(token in reply for token in ceiling_tokens) and offer != ceiling
        if proposed_was_clamped or leaked:
            reply = f"That's the best offer I can make at this stage. My offer stands at {offer:.1f} LPA."
        else:
            reply = f"{reply} My current offer is {offer:.1f} LPA."

    new_round = int(state["round"]) + 1
    if status == "ongoing" and new_round >= MAX_ROUNDS:
        status = "timeout"
        final = None

    return {
        "messages": [AIMessage(content=reply)],
        "current_offer": offer,
        "round": new_round,
        "status": status,
        "final_offer": final,
    }


def compute_result_score(state: State) -> float:
    """Salary outcome score from 0 to 40 for a valid completed deal."""
    final_offer = state.get("final_offer")
    if state.get("status") not in {"accepted", "deal_reached"} or final_offer is None:
        return 0.0

    opening = float(state["opening_offer"])
    ceiling = float(state["budget_ceiling"])
    final = float(final_offer)

    if not (0 < opening <= ceiling):
        raise ValueError(f"Invalid opening/ceiling: {opening}/{ceiling}")
    if not (opening <= final <= ceiling):
        raise ValueError(
            f"Invalid final offer: opening={opening}, final={final}, ceiling={ceiling}"
        )

    room = ceiling - opening
    if room <= 0:
        return 0.0

    return round(max(0.0, min(40.0, 40.0 * (final - opening) / room)), 1)


def coach(state: State) -> dict:

    """Evaluate the negotiation using validated structured output only."""

    result_score = compute_result_score(state)

    transcript = "\n".join(

        f"{'Recruiter' if message.type == 'ai' else 'Candidate'}: {message.content}"

        for message in state["messages"]

    )

    prompt = SystemMessage(

        content=(

            "You are a salary-negotiation coach. Evaluate the candidate using the facts and "

            "transcript below. Return only fields required by the structured schema. "

            "The result score is fixed and must not be changed; do not include it in the other "

            "category scores. Give exactly three specific tips. "

            "If the outcome is 'timeout', the recruiter's last offer stood when time ran out.\n\n"

            f"Outcome: {state['status']}\n"

            f"Final offer: {state['final_offer']} LPA (None means no deal)\n"

            f"Opening offer: {state['opening_offer']} LPA\n"

            f"Recruiter's hidden maximum budget: {state['budget_ceiling']} LPA\n"

            f"Recruiter personality: {state['personality']}\n"

            f"Fixed result score: {result_score}/40\n"

            f"Candidate tactics by round: {state['tactic_log']}\n\n"

            f"Transcript:\n{transcript}\n\n"

            "Score anchoring /15, justification /15, non-salary value /10, honesty/risk /10, "

            "and composure /10. Identify the biggest mistake and its round when possible. "

            "Tips should be practical and concise."

        )

    )

    structured_coach = coach_llm.with_structured_output(CoachingReport)

    try:

        report: CoachingReport = structured_coach.invoke(

            [prompt, HumanMessage(content="Return the structured coaching evaluation.")]

        )

    except Exception as exc:

        print(f"[Warning] Structured coaching failed: {type(exc).__name__}: {exc}")

        report = CoachingReport(

            anchoring_score=0,

            justification_score=0,

            non_salary_value_score=0,

            honesty_risk_score=0,

            composure_score=0,

            biggest_mistake="A structured coaching report could not be generated.",

            biggest_mistake_round=None,

            tips=[

                "State a clear target salary.",

                "Support your request with evidence.",

                "Consider negotiating non-salary benefits.",

            ],

            explanation="The coaching model failed; review the logs and try again.",

        )

    total_score = (

        result_score

        + report.anchoring_score

        + report.justification_score

        + report.non_salary_value_score

        + report.honesty_risk_score

        + report.composure_score

    )

    money_left = (

        f"{state['budget_ceiling'] - state['final_offer']:.1f} LPA"

        if state["final_offer"] is not None

        else "No deal was reached."

    )

    mistake_round = (

        str(report.biggest_mistake_round)

        if report.biggest_mistake_round is not None

        else "unknown"

    )

    debrief = (

        f"TOTAL SCORE: {total_score:.1f}/100\n"

        f"Result: {result_score}/40\n"

        f"Anchoring: {report.anchoring_score}/15\n"

        f"Justification: {report.justification_score}/15\n"

        f"Non-salary value: {report.non_salary_value_score}/10\n"

        f"Honesty/risk: {report.honesty_risk_score}/10\n"

        f"Composure: {report.composure_score}/10\n"

        f"Money left on the table: {money_left}\n"

        f"Biggest mistake (round {mistake_round}): {report.biggest_mistake}\n"

        f"Evaluation: {report.explanation}\n"

        "Tips:\n" + "\n".join(

            f"{index}. {tip}" for index, tip in enumerate(report.tips, start=1)

        )

    )

    return {

        "debrief": debrief,

        "result_score": result_score,

        "coaching_report": report.model_dump(),

    }

# --- Routing ---------------------------------------------------------------

def after_user(state: State) -> str:

    return "finalize" if state["quit"] else "tactic_analyzer"

def after_analyzer(state: State) -> str:

    return "finalize" if (state["user_accepts"] or state["user_walks"]) else "recruiter"

def after_guard(state: State) -> str:

    return "coach" if state["status"] != "ongoing" else "user_turn"

# --- Graph -----------------------------------------------------------------

def build_app(checkpointer):

    g = StateGraph(State)

    g.add_node("scenario", scenario)

    g.add_node("user_turn", user_turn)

    g.add_node("tactic_analyzer", tactic_analyzer)

    g.add_node("finalize", finalize)

    g.add_node("recruiter", recruiter)

    g.add_node("guard", guard)

    g.add_node("coach", coach)

    g.add_edge(START, "scenario")

    g.add_edge("scenario", "user_turn")

    g.add_conditional_edges(

        "user_turn", after_user, {"finalize": "finalize", "tactic_analyzer": "tactic_analyzer"}

    )

    g.add_conditional_edges(

        "tactic_analyzer", after_analyzer, {"finalize": "finalize", "recruiter": "recruiter"}

    )

    g.add_edge("recruiter", "guard")

    g.add_conditional_edges("guard", after_guard, {"coach": "coach", "user_turn": "user_turn"})

    g.add_edge("finalize", "coach")

    g.add_edge("coach", END)

    return g.compile(checkpointer=checkpointer)

# --- Results tables (plain SQL, separate from the checkpoint tables) -----------

def create_result_tables(conn) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS game_results (

            game_id       TEXT PRIMARY KEY,

            status        TEXT,

            personality   TEXT,

            opening_offer REAL,

            ceiling       REAL,

            final_offer   REAL,

            result_score  REAL,

            rounds        INT,

            coaching_report JSONB,

            finished_at   TIMESTAMPTZ DEFAULT now()

        )

        """

    )

    conn.execute("ALTER TABLE game_results ADD COLUMN IF NOT EXISTS coaching_report JSONB")

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS game_tactics (

            game_id TEXT REFERENCES game_results(game_id) ON DELETE CASCADE,

            round   INT,

            tactic  TEXT,

            PRIMARY KEY (game_id, round, tactic)

        )

        """

    )

    conn.commit()

def save_game_result(conn, game_id: str, v: dict) -> None:

    """Upsert, so saving the same finished game twice never creates duplicates."""

    conn.execute(

        """

        INSERT INTO game_results

            (game_id, status, personality, opening_offer, ceiling, final_offer, result_score, rounds, coaching_report)

        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)

        ON CONFLICT (game_id) DO UPDATE SET

            status = EXCLUDED.status,

            personality = EXCLUDED.personality,

            opening_offer = EXCLUDED.opening_offer,

            ceiling = EXCLUDED.ceiling,

            final_offer = EXCLUDED.final_offer,

            result_score = EXCLUDED.result_score,

            rounds = EXCLUDED.rounds,

            coaching_report = EXCLUDED.coaching_report

        """,

        (

            game_id,

            v["status"],

            v["personality"],

            v["opening_offer"],

            v["budget_ceiling"],

            v["final_offer"],

            v["result_score"],

            v["round"],

            Jsonb(v.get("coaching_report", {})),

        ),

    )

    conn.execute("DELETE FROM game_tactics WHERE game_id = %s", (game_id,))

    for entry in v["tactic_log"]:

        for tactic in entry["tactics"]:

            conn.execute(

                """

                INSERT INTO game_tactics (game_id, round, tactic)

                VALUES (%s, %s, %s)

                ON CONFLICT DO NOTHING

                """,

                (game_id, entry["round"], tactic),

            )

    conn.commit()

def print_stats(conn) -> None:

    """Average score per personality, across every game you have finished."""

    rows = conn.execute(

        """

        SELECT personality, COUNT(*) AS games, ROUND(AVG(result_score)::numeric, 1) AS avg_score

        FROM game_results

        GROUP BY personality

        ORDER BY avg_score DESC

        """

    ).fetchall()

    if rows:

        print("\nYour record so far (average Result score by recruiter type):")

        for personality, games, avg_score in rows:

            print(f"  {personality:<10} games: {games:<3} avg score: {avg_score}/40")

# --- Resume helpers ----------------------------------------------------------

def list_games(conn, app) -> list:

    """Every saved game id, with whether it is still in progress."""

    rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()

    games = []

    for (thread_id,) in rows:

        snap = app.get_state({"configurable": {"thread_id": thread_id}})

        if snap.values:

            label = "in progress" if snap.next else "finished"

            games.append((thread_id, label, snap.values.get("round", 0)))

    return games

def show_history(values: dict) -> None:

    print("\n--- Conversation so far ---")

    for m in values.get("messages", []):

        who = "Recruiter" if m.type == "ai" else "You"

        print(f"{who}: {m.content}")

    print("---------------------------")

# --- Display helpers --------------------------------------------------------

def show_last_ai(values: dict) -> None:

    """Print the latest message only if it came from the recruiter."""

    messages = values.get("messages", [])

    if messages and messages[-1].type == "ai":

        print(f"\nRecruiter: {messages[-1].content}")

def print_summary(values: dict) -> None:

    print("\n" + "=" * 50)

    print(f"RESULT: {values['status'].upper()} | final offer: {values['final_offer']}")

    print(

        f"Recruiter's hidden ceiling: {values['budget_ceiling']} LPA "

        f"({values['personality']}, opened at {values['opening_offer']})"

    )

    score = compute_result_score(values)
    print(f"Result score: {score:.1f}/40")

    print("=" * 50)

    print(values["debrief"])

# --- The game loop (lives OUTSIDE the graph) ---------------------------------

def main():

    url = DATABASE_URL

    # Everything that uses \`app\` or \`conn\` must stay inside this with-block.

    with psycopg.connect(url) as conn, PostgresSaver.from_conn_string(url) as saver:

        saver.setup()  # creates the checkpoint tables; safe to call every time

        create_result_tables(conn)

        app = build_app(saver)

        saved = list_games(conn, app)

        if saved:

            print("Saved games:")

            for game, label, rnd in saved:

                print(f"  {game:<20} {label:<12} round {rnd}")

        game_id = input("\nGame ID (a saved id resumes it, a new name starts a new game): ").strip() or "game-1"

        # thread_id = the save slot. Same id -> same saved game.

        config = {"configurable": {"thread_id": game_id}}

        snap = app.get_state(config)

        # snap.values -> saved state ({} if this game id is new)

        # snap.next   -> nodes that run next (empty when the graph has finished)

        if not snap.values:

            result = app.invoke({}, config)  # runs scenario, then pauses at user_turn

            show_last_ai(result)

        elif not snap.next:

            print_summary(snap.values)

            print_stats(conn)

            print("\nThis game is finished. Use a new game id to play again.")

            return

        else:

            print("Resuming game...")

            show_history(snap.values)

        while app.get_state(config).next:  # still paused, waiting for the player

            values = app.get_state(config).values

            text = input(

                f"\n[Round {values['round'] + 1}/{MAX_ROUNDS} | Offer: {values['current_offer']} LPA] You: "

            )

            result = app.invoke(Command(resume=text), config)

            show_last_ai(result)

        final = app.get_state(config).values

        save_game_result(conn, game_id, final)

        print_summary(final)

        print_stats(conn)

if __name__ == "__main__":

    main()
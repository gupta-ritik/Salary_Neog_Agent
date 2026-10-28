import random
import operator
from dotenv import load_dotenv
import os
from typing import Literal, Optional, TypedDict
from langchain_groq import ChatGroq
from langchain_openrouter import ChatOpenRouter
from langchain.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from typing import Annotated
from langgraph.graph import StateGraph, START, END


load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
model = os.getenv("GROQ_MODEL")

llm=ChatGroq(model=model, api_key=GROQ_API_KEY)



MAX_ROUNDS = 4
DEBUG = True  # prints the tags each round. Turn off for the real game.
 
PERSONALITIES = {
    "hardliner": "Firm and brief. Concede only small steps, and only for strong justification.",
    "friendly": "Warm and chatty. Concede more readily, but ask for something in return.",
    "stalling": "Evasive. Say you must check with your manager. Concede only after repeated pressure.",
}
 
# Lookup table: tactic tag -> instruction for the recruiter.
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
 
# Literal = the model may ONLY choose from these exact strings.
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
 
 
# --- Structured outputs ------------------------------------------------------
class TacticTags(BaseModel):
    tactics: list[Tactic] = Field(description="Every tactic used in the candidate's latest message")
    candidate_ask: Optional[float] = Field(
        default=None, description="Salary in LPA the candidate is asking for, if they stated one"
    )
 
 
class RecruiterMove(BaseModel):
    reply: str = Field(description="What the recruiter says. Never mention the budget ceiling.")
    new_offer: float = Field(description="The recruiter's offer in LPA after this reply")
 
 
# --- State -----------------------------------------------------------------
class State(TypedDict):
    # public
    messages: Annotated[list, add_messages]
    round: int
    current_offer: float
    quit: bool
    # hidden
    budget_ceiling: float
    personality: str
    # analysis
    tactic_log: Annotated[list, operator.add]  # grows every round
    latest_tactics: list                        # overwritten every round
    candidate_ask: Optional[float]
    # drafts
    draft_reply: str
    proposed_offer: float
 
 
# --- Nodes -----------------------------------------------------------------
def scenario(state: State) -> dict:
    ceiling = random.randint(14, 30)
    opening = round(ceiling * random.uniform(0.70, 0.82), 1)
    personality = random.choice(list(PERSONALITIES))
    greeting = AIMessage(content=f"Hi! We'd like to offer you {opening} LPA. What do you think?")
    print(f"Recruiter: {greeting.content}")
    return {
        "budget_ceiling": ceiling,
        "personality": personality,
        "current_offer": opening,
        "round": 0,
        "quit": False,
        "messages": [greeting],
        "tactic_log": [],
        "latest_tactics": [],
        "candidate_ask": None,
    }
 
 
def user_turn(state: State) -> dict:
    text = input(
        f"\n[Round {state['round'] + 1}/{MAX_ROUNDS} | Offer: {state['current_offer']} LPA] You: "
    ).strip()
    return {"messages": [HumanMessage(content=text)], "quit": text.lower() == "quit"}
 
 
def tactic_analyzer(state: State) -> dict:
    """Reads ONLY the candidate's latest message and labels it."""
    last_user_text = state["messages"][-1].content
 
    # 1. Wrap the model so it must return a TacticTags object, not free text.
    analyzer = llm.with_structured_output(TacticTags)
 
    # 2. Call it. The system prompt defines the labeling job and the allowed tags.
    system = SystemMessage(
        content=(
            "You label salary-negotiation tactics used by a candidate. "
            f"The recruiter's current offer is {state['current_offer']} LPA. "
            "If the candidate accepts that offer right away, use 'accepted_too_fast'. "
            "Use only tactics from the allowed list. "
            "A claim of another offer is 'competing_offer'. "
            "Set candidate_ask only if the candidate states a salary number they want."
        )
    )
    try:
        result = analyzer.invoke([system, HumanMessage(content=last_user_text)])
    except Exception as e:
        # Free models sometimes return malformed output. Never let that crash the game.
        print(f"   [analyzer failed: {type(e).__name__}. Using fallback tags]")
        result = TacticTags(tactics=["no_clear_tactic"], candidate_ask=None)
 
    # An empty list would leave the recruiter without instructions.
    if not result.tactics:
        result.tactics = ["no_clear_tactic"]
 
    if DEBUG:
        print(f"   [DEBUG tags: {result.tactics} | ask: {result.candidate_ask}]")
 
    # 3. tactic_log has a reducer (operator.add), so we return a one-item LIST to append.
    return {
        "tactic_log": [{"round": state["round"] + 1, "tactics": result.tactics}],
        "latest_tactics": result.tactics,
        "candidate_ask": result.candidate_ask,
    }
 
 

def recruiter(state: State) -> dict:
    reactions = "\n".join(
        f"- {TACTIC_REACTIONS[t]}"
        for t in state["latest_tactics"]
    )

    system = SystemMessage(
        content=(
            "You are a recruiter negotiating a software engineer's salary.\n"
            f"Private maximum budget: {state['budget_ceiling']} LPA. "
            "Never reveal the budget ceiling.\n"
            f"Personality: {state['personality']} -> "
            f"{PERSONALITIES[state['personality']]}\n"
            f"Current offer: {state['current_offer']} LPA. "
            "Never lower it.\n"
            f"Candidate's requested salary: {state['candidate_ask']} LPA.\n"
            f"Negotiation instructions:\n{reactions}\n"
            "Keep the reply under 60 words.\n\n"
            "Return a JSON object with exactly these fields:\n"
            '{"reply": "your recruiter response", '
            '"new_offer": 21.3}\n'
            "The new_offer must be a numeric value in LPA. "
            "Do not return plain text outside the JSON object."
        )
    )

    # Use JSON mode instead of tool-calling structured output.
    mover = llm.with_structured_output(
        RecruiterMove,
        method="json_mode",
    )

    move = None

    for attempt in range(2):
        try:
            move = mover.invoke([system, *state["messages"]])

            # Validate that the proposed salary is finite.
            if not (
                float("-inf") < move.new_offer < float("inf")
            ):
                raise ValueError("Invalid salary proposal")

            break

        except Exception as e:
            print(
                f"Recruiter attempt {attempt + 1} failed: "
                f"{type(e).__name__}: {e}"
            )

    if move is None:
        print("Using safe fallback response.")

        move = RecruiterMove(
            reply=(
                "Thank you for discussing the offer. "
                "We will retain the current salary offer "
                "while reviewing your additional requests."
            ),
            new_offer=state["current_offer"],
        )

    return {
        "draft_reply": move.reply,
        "proposed_offer": move.new_offer,
    }
 
def guard(state: State) -> dict:
    ceiling = state["budget_ceiling"]
    current = state["current_offer"]
    proposed = state["proposed_offer"]
    reply = state["draft_reply"]
 
    offer = round(max(current, min(proposed, ceiling)), 1)
    was_clamped = offer != round(proposed, 1)
    leaked = str(int(ceiling)) in reply and offer != ceiling
 
    if was_clamped or leaked:
        reply = (
            "That's the most I can do within the approved range. "
            f"My offer stands at {offer} LPA."
        )
 
    print(f"\nRecruiter: {reply}")
    return {
        "messages": [AIMessage(content=reply)],
        "current_offer": offer,
        "round": state["round"] + 1,
    }
 
 
# --- Routing ---------------------------------------------------------------
def after_user(state: State) -> str:
    # 6. The analyzer now sits between user_turn and recruiter.
    return "end" if state["quit"] else "tactic_analyzer"
 
 
def after_guard(state: State) -> str:
    return "user_turn" if state["round"] < MAX_ROUNDS else "end"
 
 


# --- Graph -----------------------------------------------------------------
def build_app():
    g = StateGraph(State)
 
    # 7. Nodes
    g.add_node("scenario", scenario)
    g.add_node("user_turn", user_turn)
    g.add_node("tactic_analyzer", tactic_analyzer)
    g.add_node("recruiter", recruiter)
    g.add_node("guard", guard)
 
    # 8. Edges
    g.add_edge(START, "scenario")
    g.add_edge("scenario", "user_turn")
    g.add_conditional_edges(
        "user_turn", after_user, {"tactic_analyzer": "tactic_analyzer", "end": END}
    )
    g.add_edge("tactic_analyzer", "recruiter")
    g.add_edge("recruiter", "guard")
    g.add_conditional_edges("guard", after_guard, {"user_turn": "user_turn", "end": END})
 
    return g.compile()
 
 

if __name__ == "__main__":
    app = build_app()
    result = app.invoke({})
 
    print("\n=== GAME OVER ===")
    print(f"Final offer:        {result['current_offer']} LPA")
    print(f"Recruiter ceiling:  {result['budget_ceiling']} LPA")
    print(f"Left on the table:  {round(result['budget_ceiling'] - result['current_offer'], 1)} LPA")
    print(f"Personality:        {result['personality']}")
    print("\nYour tactics by round:")
    for entry in result["tactic_log"]:
        print(f"  Round {entry['round']}: {entry['tactics']}")
 

from dotenv import load_dotenv
import os 
from langchain_groq import ChatGroq
from typing import TypedDict,Annotated
from langgraph.graph import StateGraph, START,END
from langgraph.graph import add_messages
from langchain.messages import HumanMessage,AIMessage,SystemMessage
load_dotenv()
from pydantic import BaseModel, Field
import random
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")

llm=ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY)

MAX_ROUNDS = 4

PERSONALITIES = {
    "hardliner": "Firm and brief. Concede only small steps, and only for strong justification.",
    "friendly": "Warm and chatty. Concede more readily, but ask for something in return.",
    "stalling": "Evasive. Say you must check with your manager. Concede only after repeated pressure.",
}


# --- State -----------------------------------------------------------------
class State(TypedDict):
    # public: the UI may show these during the game
    messages: Annotated[list, add_messages]
    round: int
    current_offer: float
    quit: bool
    # hidden: only the recruiter and guard nodes may use these
    budget_ceiling: float
    personality: str
    # drafts: recruiter output waiting for the guard's approval
    draft_reply: str
    proposed_offer: float


# --- What the LLM must return (a small preview of Stage 4) -------------------
class RecruiterMove(BaseModel):
    reply: str = Field(description="What the recruiter says. Never mention the budget ceiling.")
    new_offer: float = Field(description="The recruiter's offer in LPA after this reply")


# --- Nodes -----------------------------------------------------------------
def scenario(state: State) -> dict:
    """Creates a different hidden setup every game."""
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
    }


def user_turn(state: State) -> dict:
    text = input(
        f"\n[Round {state['round'] + 1}/{MAX_ROUNDS} | Offer: {state['current_offer']} LPA] You: "
    ).strip()
    return {"messages": [HumanMessage(content=text)], "quit": text.lower() == "quit"}


def recruiter(state: State) -> dict:
    """Drafts a move. It does NOT add to the chat. The guard does that."""
    system = SystemMessage(
        content=(
            "You are a recruiter negotiating a software engineer's salary.\n"
            f"PRIVATE max budget: {state['budget_ceiling']} LPA. Never reveal or hint at it.\n"
            f"Personality: {state['personality']} -> {PERSONALITIES[state['personality']]}\n"
            f"Your current offer is {state['current_offer']} LPA. Never lower it.\n"
            "Raise it only when the candidate gives a good reason. Keep the reply under 60 words."
        )
    )
    mover = llm.with_structured_output(RecruiterMove)
    move = mover.invoke([system, *state["messages"]])
    return {"draft_reply": move.reply, "proposed_offer": move.new_offer}


def guard(state: State) -> dict:
    """Hard rules in plain Python. LLMs do language, code does constraints."""
    ceiling = state["budget_ceiling"]
    current = state["current_offer"]
    proposed = state["proposed_offer"]
    reply = state["draft_reply"]

    # 1. Safe offer: never above the ceiling, never below the current offer.
    #    min() caps it at the ceiling; max() then stops it from going down.
    offer = max(current, min(proposed, ceiling))

    # 2. Detect problems.
    was_clamped = offer != proposed                      # the LLM asked for something illegal
    leaked = str(int(ceiling)) in reply and offer != ceiling  # real ceiling shown in text

    # 3. The draft text may mention a number the guard just changed, so the chat could
    #    contradict the state. Replace the whole reply with a safe fallback.
    if was_clamped or leaked:
        reply = (
            "That's the most I can do within the approved range. "
            f"My offer stands at {offer} LPA."
        )

    print(f"\nRecruiter: {reply}")

    # 4. Only the guard writes to the public chat and updates the offer.
    return {
        "messages": [AIMessage(content=reply)],
        "current_offer": offer,
        "round": state["round"] + 1,
    }


# --- Routing ---------------------------------------------------------------
def after_user(state: State) -> str:
    return "end" if state["quit"] else "recruiter"


def after_guard(state: State) -> str:
    return "user_turn" if state["round"] < MAX_ROUNDS else "end"


# --- Graph -----------------------------------------------------------------
def build_app():
    g = StateGraph(State)

    g.add_node("scenario", scenario)
    g.add_node("user_turn", user_turn)
    g.add_node("recruiter", recruiter)
    g.add_node("guard", guard)

    g.add_edge(START, "scenario")
    g.add_edge("scenario", "user_turn")
    g.add_conditional_edges("user_turn", after_user, {"recruiter": "recruiter", "end": END})
    g.add_edge("recruiter", "guard")
    g.add_conditional_edges("guard", after_guard, {"user_turn": "user_turn", "end": END})

    return g.compile()


if __name__ == "__main__":
    app = build_app()
    result = app.invoke({})

    # The reveal: hidden info is shown only after the game ends.
    print("\n=== GAME OVER ===")
    print(f"Final offer:        {result['current_offer']} LPA")
    print(f"Recruiter ceiling:  {result['budget_ceiling']} LPA")
    print(f"Left on the table: {round({result['budget_ceiling'] - result['current_offer']},1)} LPA")
    print(f"Personality:        {result['personality']}")

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from typing import TypedDict,Annotated
import os
from langgraph.graph import StateGraph, START,END
from langgraph.graph import add_messages
from langchain.messages import HumanMessage,AIMessage,SystemMessage
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")

llm=ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY)

BUDGET = 18      # secret maximum, in LPA
MAX_ROUNDS = 3   # how many times you get to speak


# --- State -----------------------------------------------------------------
# The state is the shared memory of the graph. Every node can read it.
class State(TypedDict):
    # add_messages is a "reducer": new messages are APPENDED to the list.
    # Without it, each node's return would overwrite the whole history.
    messages: Annotated[list, add_messages]
    round: int   # plain field: a returned value REPLACES the old one
    quit: bool   # set to True when the user types 'quit'


# --- Nodes -----------------------------------------------------------------
# A node = a normal Python function. Input: state. Output: a dict containing
# ONLY the keys you want to update. LangGraph merges it into the state.
def user_turn(state: State) -> dict:
    text = input(f"\n[Round {state['round'] + 1}/{MAX_ROUNDS}] You: ").strip()
    return {
        "messages": [HumanMessage(content=text)],
        "quit": text.lower() == "quit",
    }


def recruiter(state: State) -> dict:
    # The system prompt carries the secret. The user never sees it, but the
    # model does. (In Stage 3 we add a guard node because prompts alone leak.)
    system = SystemMessage(
        content=(
            "You are a recruiter negotiating a software engineer's salary. "
            f"Your maximum budget is {BUDGET} LPA. NEVER reveal this number or hint at it. "
            "Start low, concede slowly, and only raise your offer when the candidate "
            "gives a good reason. Never offer more than your maximum. "
            "Keep replies under 60 words."
        )
    )
    # The model sees: system prompt + the whole conversation so far.
    reply = llm.invoke([system, *state["messages"]])

    print(f"\nRecruiter: {reply.content}")
    return {"messages": [reply], "round": state["round"] + 1}


# --- Routing (conditional edges) -------------------------------------------
# A routing function reads the state and returns a LABEL (a string).
# The mapping in add_conditional_edges turns that label into the next node.
def after_user(state: State) -> str:
    return "end" if state["quit"] else "recruiter"


def after_recruiter(state: State) -> str:
    return "user_turn" if state["round"] < MAX_ROUNDS else "end"



##### Build Graph ####
def build_app():
    g=StateGraph(State)

    g.add_node("user_turn",user_turn)
    g.add_node("recruiter",recruiter)

    g.add_edge(START,"user_turn")
    g.add_conditional_edges("user_turn",after_user,{"recruiter":"recruiter","end":END})
    g.add_conditional_edges("recruiter",after_recruiter,{"user_turn":"user_turn","end":END})

    return g.compile()
    



if __name__ == "__main__":
    app = build_app()

    opening = AIMessage(content="Hi! We'd like to offer you 12 LPA. What do you think?")
    print(f"Recruiter: {opening.content}")

    # The initial state must include every key your nodes read.
    result = app.invoke({"messages": [opening], "round": 0, "quit": False})

    print("\n--- Full conversation ---")
    for m in result["messages"]:
        who = "Recruiter" if m.type == "ai" else "You"
        print(f"{who}: {m.content}")

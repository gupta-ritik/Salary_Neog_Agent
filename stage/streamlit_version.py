import os
from datetime import datetime

import pandas as pd
import streamlit as st
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import complete_stage6 as game  # importing loads .env and builds the models

game.DEBUG = False  # no console debug output in the UI

MAX_ROUNDS = game.MAX_ROUNDS

STATUS_TEXT = {
    "accepted": "You accepted the offer",
    "deal_reached": "Deal reached: the recruiter accepted your ask",
    "walked_away": "You walked away",
    "recruiter_walked": "The recruiter walked away",
    "timeout": "Time ran out: the last offer stood",
}

st.set_page_config(page_title="Salary Negotiation Simulator", page_icon="💼", layout="centered")


# ----------------------------------------------------------------------------
# Database and graph (created once, then reused on every rerun)
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner="Connecting to the database...")
def get_resources():
    pool = ConnectionPool(
        conninfo=os.environ["DATABASE_URL"],
        max_size=5,
        # autocommit + dict_row are required by PostgresSaver when you pass your own connections.
        # prepare_threshold=0 avoids prepared-statement errors on pooled connections.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=ConnectionPool.check_connection,  # drops connections Neon closed while idle
        open=True,
    )
    saver = PostgresSaver(pool)
    saver.setup()
    with pool.connection() as conn:
        game.create_result_tables(conn)
    return pool, game.build_app(saver)


pool, app = get_resources()


def cfg(game_id: str) -> dict:
    return {"configurable": {"thread_id": game_id}}


def run_sql(sql: str, params=None) -> list:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def saved_games(limit: int = 20) -> list:
    """[(game_id, 'in progress' | 'finished'), ...], newest first."""
    rows = run_sql("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id DESC LIMIT %s", (limit,))
    games = []
    for row in rows:
        snap = app.get_state(cfg(row["thread_id"]))
        if snap.values:
            games.append((row["thread_id"], "in progress" if snap.next else "finished"))
    return games


def start_new_game() -> None:
    game_id = f"game-{datetime.now():%m%d-%H%M%S}"
    with st.spinner("Setting up your negotiation..."):
        app.invoke({}, cfg(game_id))  # runs `scenario`, then pauses at the first user turn
    st.session_state.game_id = game_id
    st.rerun()


if "saved_ids" not in st.session_state:
    st.session_state.saved_ids = set()  # finished games already written to the results tables

# ----------------------------------------------------------------------------
# Sidebar: pick or start a game
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Your games")
    if st.button("New game", type="primary", use_container_width=True):
        start_new_game()

    games = saved_games()
    if games:
        ids = [g for g, _ in games]
        labels = dict(games)
        current = st.session_state.get("game_id")
        index = ids.index(current) if current in ids else 0
        choice = st.selectbox(
            "Resume or review a game",
            ids,
            index=index,
            format_func=lambda g: f"{g}  ({labels[g]})",
        )
        st.session_state.game_id = choice
    else:
        st.caption("No saved games yet. Start your first one.")

    st.divider()
    st.caption(f"{MAX_ROUNDS} rounds per game. The recruiter has a hidden budget and personality.")

tab_play, tab_stats = st.tabs(["Play", "Stats"])

# ----------------------------------------------------------------------------
# Play tab
# ----------------------------------------------------------------------------
with tab_play:
    st.title("💼 Salary Negotiation Simulator")
    game_id = st.session_state.get("game_id")

    if not game_id:
        st.info("Press **New game** in the sidebar to start negotiating.")
    else:
        config = cfg(game_id)
        snap = app.get_state(config)
        values = snap.values
        in_progress = bool(snap.next)

        def submit(text: str) -> None:
            """Send the player's message into the paused graph and refresh."""
            st.chat_message("user").write(text)
            with st.spinner("The recruiter is thinking..."):
                try:
                    app.invoke(Command(resume=text), config)
                except Exception as exc:  # the checkpoint is safe, so the player can retry
                    st.error(f"Something went wrong: {type(exc).__name__}: {exc}. Your game is saved, try again.")
                    return
            st.rerun()

        # Public information only. Never show budget_ceiling or personality here.
        col1, col2, col3 = st.columns(3)
        col1.metric("Round", f"{min(values['round'] + 1, MAX_ROUNDS)}/{MAX_ROUNDS}")
        col2.metric("Current offer", f"{values['current_offer']} LPA")
        col3.metric("Status", "In progress" if in_progress else "Finished")
        st.caption(f"Game id: {game_id}")

        for message in values["messages"]:
            if message.type == "ai":
                st.chat_message("assistant", avatar="💼").write(message.content)
            else:
                st.chat_message("user").write(message.content)

        if in_progress:
            if st.button("Walk away", help="End the negotiation with no deal"):
                submit("quit")
            text = st.chat_input("Your reply: state a number, give a reason, ask about perks...")
            if text:
                submit(text)
        else:
            # ---------------- Results screen: hidden info is revealed here ----------------
            if game_id not in st.session_state.saved_ids:
                with pool.connection() as conn:
                    game.save_game_result(conn, game_id, values)
                st.session_state.saved_ids.add(game_id)

            st.divider()
            st.subheader(STATUS_TEXT.get(values["status"], values["status"]))

            final_offer = values["final_offer"]
            ceiling = values["budget_ceiling"]
            reveal = st.columns(4)
            reveal[0].metric("Opening offer", f"{values['opening_offer']} LPA")
            reveal[1].metric("Your final offer", f"{final_offer} LPA" if final_offer is not None else "No deal")
            reveal[2].metric("Recruiter's ceiling", f"{ceiling} LPA")
            reveal[3].metric("Left on the table", f"{round(ceiling - final_offer, 1)} LPA" if final_offer is not None else "n/a")
            st.caption(f"The recruiter's personality was: **{values['personality']}**")

            report = values.get("coaching_report") or {}
            if report:
                rows = [
                    ("Result", values["result_score"], 40),
                    ("Anchoring", report.get("anchoring_score", 0), 15),
                    ("Justification", report.get("justification_score", 0), 15),
                    ("Non-salary value", report.get("non_salary_value_score", 0), 10),
                    ("Honesty / risk", report.get("honesty_risk_score", 0), 10),
                    ("Composure", report.get("composure_score", 0), 10),
                ]
                total = sum(score for _, score, _ in rows)
                st.metric("Total score", f"{total:.0f} / 100")
                for label, score, maximum in rows:
                    st.progress(min(score / maximum, 1.0), text=f"{label}: {score}/{maximum}")

                mistake_round = report.get("biggest_mistake_round")
                st.markdown(
                    f"**Biggest mistake" + (f" (round {mistake_round})" if mistake_round else "") + f":** {report.get('biggest_mistake', '')}"
                )
                st.markdown("**Tips for next time**")
                for tip in report.get("tips", []):
                    st.markdown(f"- {tip}")
                with st.expander("Full coach evaluation"):
                    st.write(report.get("explanation", ""))
                    st.text(values["debrief"])
            else:
                st.text(values["debrief"])

            if st.button("Play again", type="primary"):
                start_new_game()

# ----------------------------------------------------------------------------
# Stats tab: analytics across all finished games (SQL on Neon)
# ----------------------------------------------------------------------------
with tab_stats:
    st.header("Your negotiation record")
    results = run_sql(
        """
        SELECT game_id, status, personality, opening_offer, ceiling, final_offer,
               result_score, rounds, finished_at
        FROM game_results ORDER BY finished_at DESC
        """
    )
    if not results:
        st.info("Finish a game and open it here to see your stats.")
    else:
        df = pd.DataFrame(results)
        a, b, c = st.columns(3)
        a.metric("Games finished", len(df))
        b.metric("Average result score", f"{df['result_score'].mean():.1f} / 40")
        c.metric("Best result score", f"{df['result_score'].max():.1f} / 40")

        st.subheader("Average result score by recruiter type")
        by_personality = pd.DataFrame(
            run_sql(
                """
                SELECT personality, COUNT(*)::int AS games,
                       ROUND(AVG(result_score)::numeric, 1)::float AS avg_score
                FROM game_results GROUP BY personality ORDER BY avg_score DESC
                """
            )
        )
        st.bar_chart(by_personality.set_index("personality")["avg_score"])

        st.subheader("Which tactics go with higher scores?")
        by_tactic = pd.DataFrame(
            run_sql(
                """
                SELECT t.tactic, COUNT(DISTINCT t.game_id)::int AS games,
                       ROUND(AVG(g.result_score)::numeric, 1)::float AS avg_score
                FROM game_tactics t JOIN game_results g USING (game_id)
                GROUP BY t.tactic ORDER BY avg_score DESC
                """
            )
        )
        if not by_tactic.empty:
            st.dataframe(by_tactic, hide_index=True, use_container_width=True)
            st.caption("With few games these averages are noisy. Play more games for clearer patterns.")

        st.subheader("All games")
        st.dataframe(df, hide_index=True, use_container_width=True)
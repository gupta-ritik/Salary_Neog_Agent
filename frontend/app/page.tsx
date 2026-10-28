"use client";



import { useCallback, useEffect, useState } from "react";

import PerformancePanel from "./performance-panel";

import {

  api,

  type Game,

  type GameSummary,

  type StatsResponse,
  type CoachingResponse,

} from "@/lib/api";



type GameFilter = "all" | "active" | "completed";



export default function Home() {

  const [game, setGame] = useState<Game | null>(null);

  const [games, setGames] = useState<GameSummary[]>([]);

  const [stats, setStats] = useState<StatsResponse | null>(null);

  const [message, setMessage] = useState("");

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState("");

  const [gameFilter, setGameFilter] = useState<GameFilter>("all");



  // Load all saved games from FastAPI

  const refreshGames = useCallback(async () => {

    const data = await api.listGames();

    setGames(data);

  }, []);



  // Load games and statistics on page mount

  useEffect(() => {

    refreshGames().catch((err) => {

      setError(

        err instanceof Error

          ? err.message

          : "Could not load saved games."

      );

    });



    api

      .getStats()

      .then(setStats)

      .catch(() => {

        // Statistics may be unavailable before games are completed.

      });

  }, [refreshGames]);



  // Filter saved games locally

  const filteredGames = games.filter((saved) => {

    if (gameFilter === "active") {

      return saved.in_progress;

    }



    if (gameFilter === "completed") {

      return !saved.in_progress;

    }



    return true;

  });



  // Shared handler for creating, resuming, and updating games

  async function handleAction(action: () => Promise<Game>) {

    setLoading(true);

    setError("");



    try {

      const updatedGame = await action();



      setGame(updatedGame);

      setMessage("");



      await refreshGames();



      api.getStats().then(setStats).catch(() => {});

    } catch (err) {

      setError(

        err instanceof Error

          ? err.message

          : "Something went wrong."

      );

    } finally {

      setLoading(false);

    }

  }



  function startNewGame() {

    void handleAction(() => api.createGame());

  }



  function resumeChat(gameId: string) {

    void handleAction(() => api.resumeGame(gameId));

  }



  function sendMessage(event: React.FormEvent<HTMLFormElement>) {

    event.preventDefault();



    if (!game || !game.in_progress || !message.trim() || loading) {

      return;

    }



    const text = message.trim();



    void handleAction(() => api.sendMessage(game.id, text));

  }



  async function handleRefresh() {

    setLoading(true);

    setError("");



    try {

      await refreshGames();

      const updatedStats = await api.getStats().catch(() => null);



      if (updatedStats) {

        setStats(updatedStats);

      }

    } catch (err) {

      setError(

        err instanceof Error

          ? err.message

          : "Could not refresh games."

      );

    } finally {

      setLoading(false);

    }

  }



  const activeCount = games.filter((g) => g.in_progress).length;

  const completedCount = games.filter((g) => !g.in_progress).length;



  return (

    <main className="min-h-screen overflow-x-hidden bg-violet-50 text-violet-950">

      <div className="mx-auto w-full max-w-7xl space-y-6 px-3 py-5 sm:space-y-8 sm:px-6 sm:py-8 lg:px-8">

        {/* Header */}

        <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">

          <div>

            <p className="text-sm font-medium text-violet-600">

              AI-POWERED SIMULATION

            </p>



            <h1 className="mt-2 text-3xl font-bold sm:text-4xl">

              Salary Negotiation Agent

            </h1>



            <p className="mt-2 text-violet-600">

              Practice negotiation, improve your strategy, and evaluate

              your performance.

            </p>

          </div>



          <button

            type="button"

            onClick={startNewGame}

            disabled={loading}

            className="w-full rounded-xl bg-violet-600 px-5 py-3 font-semibold transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"

          >

            + New Game

          </button>

        </header>

        <PerformancePanel />

        {/* Error message */}

        {error && (

          <div

            role="alert"

            className="rounded-xl border border-red-800 bg-red-950/50 p-4 text-red-300"

          >

            {error}

          </div>

        )}



        {/* Statistics */}

        <section className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">

          <StatCard

            title="Completed Games"

            value={stats?.summary.games ?? 0}

          />



          <StatCard

            title="Average Result Score"

            value={`${stats?.summary.avg_score ?? 0}/40`}

          />



          <StatCard

            title="Best Result Score"

            value={`${stats?.summary.best_score ?? 0}/40`}

          />

        </section>



        <div className="grid min-w-0 grid-cols-1 gap-5 lg:grid-cols-[minmax(260px,320px)_minmax(0,1fr)] lg:gap-8">

          {/* Saved Games Sidebar */}

          <aside className="h-fit min-w-0 overflow-hidden rounded-2xl border border-violet-100 bg-white p-4 sm:p-5">

            <div className="flex items-center justify-between gap-2">

              <h2 className="text-xl font-semibold">Saved Games</h2>



              <button

                type="button"

                onClick={handleRefresh}

                disabled={loading}

                className="rounded-lg border border-violet-200 px-3 py-2 text-sm hover:bg-violet-100 disabled:opacity-50"

              >

                Refresh

              </button>

            </div>



            <p className="mt-2 text-sm text-violet-600">

              Continue unfinished negotiations or review completed games.

            </p>



            {/* Game Filters */}

            <div className="mt-5 grid grid-cols-3 gap-1 sm:gap-2">

              {(

                [

                  { label: "All", value: "all" },

                  { label: "Active", value: "active" },

                  { label: "Completed", value: "completed" },

                ] as const

              ).map((filter) => {

                const count =

                  filter.value === "all"

                    ? games.length

                    : filter.value === "active"

                      ? activeCount

                      : completedCount;



                const selected = gameFilter === filter.value;



                return (

                  <button

                    key={filter.value}

                    type="button"

                    onClick={() => setGameFilter(filter.value)}

                    aria-pressed={selected}

                    className={`rounded-lg px-1 py-2 text-xs font-medium transition sm:px-2 sm:text-sm ${

                      selected

                        ? "bg-violet-600 text-white"

                        : "bg-violet-100 text-violet-600 hover:bg-violet-200 hover:text-white"

                    }`}

                  >

                    {filter.label} ({count})

                  </button>

                );

              })}

            </div>



            {/* Filtered Games */}

            <div className="mt-4 max-h-[420px] space-y-3 overflow-y-auto overscroll-contain pr-1 lg:max-h-[65vh]">

              {filteredGames.length === 0 ? (

                <p className="rounded-xl bg-violet-100/60 p-4 text-sm text-violet-600">

                  {gameFilter === "active"

                    ? "No active games. Start a new negotiation."

                    : gameFilter === "completed"

                      ? "No completed games yet."

                      : "No saved games found. Start a new game to begin."}

                </p>

              ) : (

                filteredGames.map((saved) => (

                  <button

                    key={saved.id}

                    type="button"

                    onClick={() => resumeChat(saved.id)}

                    disabled={loading}

                    className={`w-full min-w-0 rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50 sm:p-4 ${

                      game?.id === saved.id

                        ? "border-violet-500 bg-blue-950/40"

                        : "border-violet-100 bg-violet-50 hover:border-violet-400"

                    }`}

                  >

                    <div className="flex items-start justify-between gap-2">

                      <span className="break-all font-medium">

                        {saved.id}

                      </span>



                      <span

                        className={`shrink-0 rounded-full px-2 py-1 text-xs ${

                          saved.in_progress

                            ? "bg-emerald-950 text-emerald-300"

                            : "bg-violet-100 text-violet-600"

                        }`}

                      >

                        {saved.in_progress ? "Active" : "Completed"}

                      </span>

                    </div>



                    <div className="mt-3 space-y-1 text-sm text-violet-600">

                      <p>Round: {saved.round}</p>

                      <p>Current offer: {saved.current_offer} LPA</p>

                      <p>Status: {saved.status}</p>

                    </div>



                    <p className="mt-3 text-sm font-semibold text-violet-600">

                      {saved.in_progress

                        ? "Resume Chat →"

                        : "View Result →"}

                    </p>

                  </button>

                ))

              )}

            </div>

          </aside>



          {/* Main Game Panel */}

          <section className="min-w-0 overflow-hidden rounded-2xl border border-violet-100 bg-white">

            {!game ? (

              <div className="flex min-h-[420px] flex-col items-center justify-center px-6 py-12 text-center">

                <div className="text-5xl">💼</div>



                <h2 className="mt-5 text-2xl font-bold">

                  Ready to negotiate?

                </h2>



                <p className="mt-3 max-w-md text-violet-600">

                  Start a new simulation or select a saved game to

                  continue where you left off.

                </p>



                <button

                  type="button"

                  onClick={startNewGame}

                  disabled={loading}

                  className="mt-6 rounded-xl bg-violet-600 px-6 py-3 font-semibold hover:bg-violet-500 disabled:opacity-50"

                >

                  {loading ? "Loading..." : "Start Negotiation"}

                </button>

              </div>

            ) : (

              <>

                {/* Game Information */}

                <div className="border-b border-violet-100 p-4 sm:p-6">

                  <div className="flex flex-col justify-between gap-4 sm:flex-row">

                    <div>

                      <h2 className="text-xl font-bold">

                        {game.in_progress

                          ? "Negotiation Chat"

                          : "Negotiation Results"}

                      </h2>



                      <p className="mt-1 break-all text-sm text-violet-600">

                        Game ID: {game.id}

                      </p>

                    </div>



                    <span className="h-fit w-fit rounded-full bg-violet-100 px-3 py-1 text-sm">

                      {game.status}

                    </span>

                  </div>



                  <div className="mt-4 grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 sm:mt-5 sm:grid-cols-3">

                    <MiniStat

                      title="Round"

                      value={`${game.round}/${game.max_rounds}`}

                    />



                    <MiniStat

                      title="Current Offer"

                      value={`${game.current_offer} LPA`}

                    />



                    <MiniStat

                      title="Opening Offer"

                      value={`${game.opening_offer} LPA`}

                    />

                  </div>

                </div>



                                {/* Strategy Analysis */}
                {game.in_progress && game.strategy_analysis && (
                  <section className="mx-3 mt-4 rounded-2xl border border-indigo-800/70 bg-indigo-950/30 p-4 sm:mx-5 sm:mt-5 sm:p-5 lg:mx-6">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-xl">
                        🧠
                      </div>
                      <div>
                        <h3 className="font-semibold text-indigo-200">
                          Strategy Analysis
                        </h3>
                        <p className="text-sm text-violet-600">
                          Recruiter strategy planner
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="rounded-xl bg-violet-50/70 p-4">
                        <p className="text-xs font-medium uppercase tracking-wide text-violet-500">
                          Planned Action
                        </p>
                        <p className="mt-2 break-words font-semibold capitalize text-violet-950">
                          {game.strategy_analysis.planned_action ?? "Not available"}
                        </p>
                      </div>

                      <div className="rounded-xl bg-violet-50/70 p-4">
                        <p className="text-xs font-medium uppercase tracking-wide text-violet-500">
                          Planned Offer
                        </p>
                        <p className="mt-2 font-semibold text-violet-950">
                          {game.strategy_analysis.planned_offer != null
                            ? `${game.strategy_analysis.planned_offer} LPA`
                            : "Not available"}
                        </p>
                      </div>

                      <div className="rounded-xl bg-violet-50/70 p-4 sm:col-span-2">
                        <p className="text-xs font-medium uppercase tracking-wide text-violet-500">
                          Next Objective
                        </p>
                        <p className="mt-2 whitespace-pre-wrap break-words leading-6 text-violet-900">
                          {game.strategy_analysis.next_objective ?? "Not available"}
                        </p>
                      </div>
                    </div>
                  </section>
                )}

{/* Conversation History */}

                <div className="max-h-[55vh] min-h-[180px] space-y-4 overflow-y-auto overscroll-contain p-3 sm:max-h-[560px] sm:space-y-5 sm:p-6">

                  {game.messages.map((item, index) => {

                    const isRecruiter = item.role === "recruiter";



                    return (

                      <div

                        key={`${game.id}-${index}`}

                        className={`flex ${

                          isRecruiter ? "justify-start" : "justify-end"

                        }`}

                      >

                        <div

                          className={`max-w-[95%] break-words rounded-2xl p-3 sm:max-w-[80%] sm:p-4 ${

                            isRecruiter

                              ? "rounded-tl-sm bg-violet-100"

                              : "rounded-tr-sm bg-blue-700"

                          }`}

                        >

                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide opacity-70">

                            {isRecruiter ? "AI Recruiter" : "You"}

                          </p>



                          <p className="whitespace-pre-wrap break-words leading-7">

                            {item.content}

                          </p>

                        </div>

                      </div>

                    );

                  })}



                  {loading && (

                    <p className="text-sm text-blue-300">

                      Processing your request...

                    </p>

                  )}

                </div>



                {/* Message Input */}

                {game.in_progress ? (

                  <form

                    onSubmit={sendMessage}

                    className="border-t border-violet-100 p-4 sm:p-6"

                  >

                    <label

                      htmlFor="negotiation-message"

                      className="mb-2 block text-sm font-medium text-violet-800"

                    >

                      Your negotiation response

                    </label>



                    <textarea

                      id="negotiation-message"

                      value={message}

                      onChange={(event) => setMessage(event.target.value)}

                      placeholder="Example: Based on my skills and market compensation, I was expecting 19 LPA..."

                      maxLength={1000}

                      rows={4}

                      required

                      disabled={loading}

                      className="w-full min-w-0 resize-y rounded-xl border border-violet-200 bg-violet-50 p-3 outline-none transition placeholder:text-violet-400 focus:border-violet-500 disabled:opacity-50 sm:p-4"

                    />



                    <div className="mt-3 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">

                      <p className="text-xs text-violet-500">

                        Maximum 1,000 characters.

                      </p>



                      <button

                        type="submit"

                        disabled={loading || !message.trim()}

                        className="rounded-xl bg-violet-600 px-5 py-3 font-semibold hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"

                      >

                        {loading

                          ? "Recruiter is thinking..."

                          : "Send Message →"}

                      </button>

                    </div>

                  </form>

                ) : (

                  <div className="border-t border-violet-100 p-4 sm:p-6">

                    {game.result ? (

                      <ResultPanel result={game.result} gameId={game.id} />

                    ) : (

                      <p className="text-violet-600">

                        This game is finished. No additional messages can

                        be sent.

                      </p>

                    )}



                    <button

                      type="button"

                      onClick={startNewGame}

                      disabled={loading}

                      className="mt-5 rounded-xl bg-violet-600 px-5 py-3 font-semibold hover:bg-violet-500 disabled:opacity-50"

                    >

                      Start New Game

                    </button>

                  </div>

                )}

              </>

            )}

          </section>

        </div>

      </div>

    </main>

  );

}



// --------------------------------------------------

// Reusable Components

// --------------------------------------------------



function StatCard({

  title,

  value,

}: {

  title: string;

  value: string | number;

}) {

  return (

    <div className="rounded-2xl border border-violet-100 bg-white p-4 sm:p-5">

      <p className="text-sm text-violet-600">{title}</p>

      <p className="mt-2 text-2xl font-bold">{value}</p>

    </div>

  );

}



function MiniStat({

  title,

  value,

}: {

  title: string;

  value: string;

}) {

  return (

    <div className="rounded-xl bg-violet-50 p-3">

      <p className="text-xs text-violet-500">{title}</p>

      <p className="mt-1 break-words font-semibold">{value}</p>

    </div>

  );

}



// --------------------------------------------------

// Final Result and Coaching Report

// --------------------------------------------------



function ResultPanel({

  result,
  gameId,

}: {

  result: NonNullable<Game["result"]>;
  gameId: string;

}) {

  const coaching = result.coaching_report;



  const coachingTotal =

    (coaching.anchoring_score ?? 0) +

    (coaching.justification_score ?? 0) +

    (coaching.non_salary_value_score ?? 0) +

    (coaching.honesty_risk_score ?? 0) +

    (coaching.composure_score ?? 0);



  const totalScore =

    result.total_score ?? result.result_score + coachingTotal;



  return (

    <div className="space-y-5">

      <h3 className="text-xl font-bold">Final Performance</h3>



      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">

        <div className="rounded-xl bg-violet-50 p-4">

          <p className="text-sm text-violet-600">Final Offer</p>

          <p className="mt-2 text-2xl font-bold">

            {result.final_offer == null

              ? "No deal"

              : `${result.final_offer} LPA`}

          </p>

        </div>



        <div className="rounded-xl bg-violet-50 p-4">

          <p className="text-sm text-violet-600">

            Money Left on the Table

          </p>

          <p className="mt-2 text-2xl font-bold">

            {result.left_on_table == null

              ? "N/A"

              : `${result.left_on_table} LPA`}

          </p>

        </div>



        <div className="rounded-xl bg-violet-50 p-4">

          <p className="text-sm text-violet-600">Negotiation Score</p>

          <p className="mt-2 text-2xl font-bold">

            {result.result_score}/40

          </p>

        </div>



        <div className="rounded-xl bg-violet-50 p-4">

          <p className="text-sm text-violet-600">Overall Score</p>

          <p className="mt-2 text-2xl font-bold">

            {totalScore}/100

          </p>

        </div>

      </div>



      {/* Coaching Breakdown */}

      <div className="space-y-3">

        <h4 className="font-semibold">Coaching Breakdown</h4>



        <ScoreRow

          label="Anchoring"

          score={coaching.anchoring_score ?? 0}

          max={15}

        />



        <ScoreRow

          label="Justification"

          score={coaching.justification_score ?? 0}

          max={15}

        />



        <ScoreRow

          label="Non-salary value"

          score={coaching.non_salary_value_score ?? 0}

          max={10}

        />



        <ScoreRow

          label="Honesty / Risk"

          score={coaching.honesty_risk_score ?? 0}

          max={10}

        />



        <ScoreRow

          label="Composure"

          score={coaching.composure_score ?? 0}

          max={10}

        />

      </div>



      {/* Biggest Mistake */}

      {coaching.biggest_mistake && (

        <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-4">

          <h4 className="font-semibold text-amber-300">

            Biggest Mistake

          </h4>



          <p className="mt-2 text-sm leading-6 text-violet-800">

            {coaching.biggest_mistake}

          </p>



          {coaching.biggest_mistake_round != null && (

            <p className="mt-1 text-xs text-violet-500">

              Round {coaching.biggest_mistake_round}

            </p>

          )}

        </div>

      )}



      {/* Tips */}

      {coaching.tips && coaching.tips.length > 0 && (

        <div>

          <h4 className="font-semibold">Tips for Next Time</h4>



          <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-6 text-violet-800">

            {coaching.tips.map((tip, index) => (

              <li key={index}>{tip}</li>

            ))}

          </ol>

        </div>

      )}



      {/* Explanation */}

      {coaching.explanation && (

        <p className="text-sm leading-6 text-violet-600">

          {coaching.explanation}

        </p>

      )}



      {/* On-demand AI Coach: separate from the existing in-game coaching report */}

      <AICoachPanel gameId={gameId} />

      {/* Full Evaluation */}

      <details className="min-w-0 rounded-xl border border-violet-100 p-3 sm:p-4">

        <summary className="cursor-pointer font-medium">

          Full Evaluation Report

        </summary>



        <pre className="mt-4 max-w-full whitespace-pre-wrap break-words text-xs leading-6 text-violet-800 sm:text-sm">

          {result.debrief}

        </pre>

      </details>

    </div>

  );

}



// --------------------------------------------------
// Post-game AI Negotiation Coach
// --------------------------------------------------

function AICoachPanel({ gameId }: { gameId: string }) {
  const [data, setData] = useState<CoachingResponse | null>(null);
  const [loadingCoach, setLoadingCoach] = useState(false);
  const [coachError, setCoachError] = useState("");

  async function generateCoachReport() {
    setLoadingCoach(true);
    setCoachError("");
    try {
      const response = await api.coachGame(gameId);
      setData(response);
    } catch (err) {
      setCoachError(
        err instanceof Error ? err.message : "Could not generate AI coaching."
      );
    } finally {
      setLoadingCoach(false);
    }
  }

  const report = data?.report;

  return (
    <section className="space-y-4 rounded-2xl border border-cyan-900/70 bg-cyan-950/20 p-4 sm:p-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-cyan-400">
            Post-game analysis
          </p>
          <h4 className="mt-1 text-lg font-bold">AI Negotiation Coach</h4>
          <p className="mt-1 text-sm text-violet-600">
            Transcript-based feedback, tactic scoring, and suggested responses.
          </p>
        </div>
        <button
          type="button"
          onClick={generateCoachReport}
          disabled={loadingCoach}
          className="rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loadingCoach ? "Analyzing negotiation..." : report ? "Reload saved feedback" : "Generate AI feedback"}
        </button>
      </div>

      {coachError && (
        <div role="alert" className="rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">
          {coachError}
        </div>
      )}

      {report && (
        <div className="space-y-5">
          <div className="rounded-xl bg-violet-50/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h5 className="font-semibold">Overall assessment</h5>
              <span className="rounded-full border border-violet-200 px-2 py-1 text-xs text-violet-600">
                Confidence: {report.confidence}
              </span>
            </div>
            <p className="mt-2 text-sm leading-6 text-violet-800">{report.overall_assessment}</p>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CoachEvidenceList title="Strengths" items={report.strengths} />
            <CoachEvidenceList title="Areas to improve" items={report.improvements} />
          </div>

          <div>
            <h5 className="font-semibold">Tactic scorecard</h5>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {report.tactic_scores.map((item) => (
                <div key={item.tactic} className="rounded-xl bg-violet-50/80 p-3">
                  <div className="flex justify-between gap-3 text-sm">
                    <span className="font-medium capitalize">{item.tactic.replace(/_/g, " ")}</span>
                    <span className="text-cyan-300">{item.score}/5</span>
                  </div>
                  <div className="mt-2 h-1.5 rounded-full bg-violet-100">
                    <div className="h-1.5 rounded-full bg-cyan-500" style={{ width: `${item.score * 20}%` }} />
                  </div>
                  <p className="mt-2 text-xs leading-5 text-violet-600">{item.rationale}</p>
                </div>
              ))}
            </div>
          </div>

          {report.missed_opportunities.length > 0 && (
            <div>
              <h5 className="font-semibold">Missed opportunities</h5>
              <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-6 text-violet-800">
                {report.missed_opportunities.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            </div>
          )}

          {report.suggested_responses.length > 0 && (
            <div>
              <h5 className="font-semibold">What you could say instead</h5>
              <div className="mt-2 space-y-3">
                {report.suggested_responses.map((item, i) => (
                  <div key={i} className="rounded-xl border border-violet-100 p-3">
                    <p className="text-xs font-semibold uppercase text-violet-500">{item.situation}</p>
                    <p className="mt-2 text-sm leading-6 text-violet-900">“{item.response}”</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <h5 className="font-semibold">Plan for your next negotiation</h5>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-6 text-violet-800">
              {report.next_time_plan.map((item, i) => <li key={i}>{item}</li>)}
            </ol>
          </div>

          <p className="text-xs leading-5 text-violet-500">
            {report.limitations} · Model: {data.model} · Prompt: {data.prompt_version}
            {data.cached ? " · Reused saved report" : " · Generated report"}
          </p>
        </div>
      )}
    </section>
  );
}

function CoachEvidenceList({
  title,
  items,
}: {
  title: string;
  items: CoachingResponse["report"]["strengths"];
}) {
  if (!items.length) return null;
  return (
    <div>
      <h5 className="font-semibold">{title}</h5>
      <div className="mt-2 space-y-3">
        {items.map((item, i) => (
          <article key={`${title}-${i}`} className="rounded-xl bg-violet-50/80 p-3">
            <p className="text-sm font-medium text-violet-900">{item.observation}</p>
            <p className="mt-2 text-xs leading-5 text-violet-600">Evidence: {item.evidence}</p>
            <p className="mt-2 text-sm leading-5 text-emerald-700">Try: {item.recommendation}</p>
          </article>
        ))}
      </div>
    </div>
  );
}


// --------------------------------------------------

// Score Progress Bar

// --------------------------------------------------



function ScoreRow({

  label,

  score,

  max,

}: {

  label: string;

  score: number;

  max: number;

}) {

  const percentage =

    max > 0

      ? Math.min(100, Math.max(0, (score / max) * 100))

      : 0;



  return (

    <div>

      <div className="mb-1 flex justify-between gap-3 text-sm">

        <span className="text-violet-800">{label}</span>

        <span className="text-violet-600">

          {score}/{max}

        </span>

      </div>



      <div className="h-2 overflow-hidden rounded-full bg-violet-100">

        <div

          className="h-full rounded-full bg-violet-500 transition-all"

          style={{ width: `${percentage}%` }}

        />

      </div>

    </div>

  );

}

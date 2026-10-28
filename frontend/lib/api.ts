
const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --------------------------------------------------
// Types
// --------------------------------------------------

export interface GameMessage {
  role: "recruiter" | "you";
  content: string;
}

export interface StrategyAnalysis {
  planned_action: string | null;
  planned_offer: number | null;
  next_objective: string | null;
}

export interface CoachingReport {
  anchoring_score?: number;
  justification_score?: number;
  non_salary_value_score?: number;
  honesty_risk_score?: number;
  composure_score?: number;
  biggest_mistake?: string;
  biggest_mistake_round?: number | null;
  tips?: string[];
  explanation?: string;
}


export interface CoachEvidenceItem {
  observation: string;
  evidence: string;
  recommendation: string;
}

export interface CoachTacticScore {
  tactic: string;
  score: number;
  rationale: string;
}

export interface CoachSuggestedResponse {
  situation: string;
  response: string;
}

export interface CoachingFeedback {
  overall_assessment: string;
  strengths: CoachEvidenceItem[];
  improvements: CoachEvidenceItem[];
  missed_opportunities: string[];
  tactic_scores: CoachTacticScore[];
  suggested_responses: CoachSuggestedResponse[];
  next_time_plan: string[];
  confidence: "low" | "medium" | "high";
  limitations: string;
}

export interface CoachingResponse {
  game_id: string;
  cached: boolean;
  report: CoachingFeedback;
  model: string;
  prompt_version: string;
  created_at: string;
}


export interface PerformanceMetrics {
  scope: string;
  coaching: { reports_generated: number; saved_reports_reused: number; estimated_llm_calls_avoided: number; reuse_rate_percent: number; avg_generation_latency_ms: number | null };
  redis: { cache_hits: number; cache_misses: number };
  api_latency: Record<string, { count: number; avg_ms: number; min_ms: number | null; max_ms: number }>;
  interpretation: string;
}

export interface GameResult {
  final_offer: number | null;
  ceiling: number;
  personality: string;
  left_on_table: number | null;
  result_score: number;
  total_score?: number;
  coaching_report: CoachingReport;
  debrief: string;
}

export interface Game {
  id: string;
  in_progress: boolean;
  status: string;
  round: number;
  max_rounds: number;
  current_offer: number;
  opening_offer: number;
  messages: GameMessage[];

  // Strategy Planner output from the backend
  strategy_analysis?: StrategyAnalysis | null;

  result: GameResult | null;
}

export interface GameSummary {
  id: string;
  in_progress: boolean;
  status: string;
  round: number;
  current_offer: number;
}

export interface PersonalityStats {
  personality: string;
  games: number;
  avg_score: number;
}

export interface TacticStats {
  tactic: string;
  games: number;
  avg_score: number;
}

export interface GameStats {
  game_id: string;
  status: string;
  personality: string;
  opening_offer: number;
  ceiling: number;
  final_offer: number | null;
  result_score: number | null;
  rounds: number;
  finished_at: string;
}

export interface StatsResponse {
  summary: {
    games: number;
    avg_score: number;
    best_score: number;
  };
  by_personality: PersonalityStats[];
  by_tactic: TacticStats[];
  games: GameStats[];
}

// --------------------------------------------------
// Common HTTP request helper
// --------------------------------------------------

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);

    const message =
      typeof errorData?.detail === "string"
        ? errorData.detail
        : `Request failed with status ${response.status}`;

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

// --------------------------------------------------
// API functions
// These endpoints match backend/api.py
// --------------------------------------------------

export const api = {
  // List saved games for the Resume Chat section
  listGames: (): Promise<GameSummary[]> =>
    request<GameSummary[]>("/games"),

  // Create a new salary negotiation game
  createGame: (): Promise<Game> =>
    request<Game>("/games", {
      method: "POST",
    }),

  // Load an existing game and restore its conversation
  resumeGame: (gameId: string): Promise<Game> =>
    request<Game>(
      `/games/${encodeURIComponent(gameId)}`
    ),

  // Alias for components already using getGame()
  getGame: (gameId: string): Promise<Game> =>
    request<Game>(
      `/games/${encodeURIComponent(gameId)}`
    ),

  // Submit a candidate message to the recruiter
  sendMessage: (
    gameId: string,
    text: string
  ): Promise<Game> =>
    request<Game>(
      `/games/${encodeURIComponent(gameId)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ text }),
      }
    ),

  // Retrieve completed-game statistics
  getStats: (): Promise<StatsResponse> =>
    request<StatsResponse>("/stats"),

  // Retrieve in-process performance telemetry for the comparison dashboard
  getPerformance: (): Promise<PerformanceMetrics> =>
    request<PerformanceMetrics>("/performance"),

  // Generate or retrieve the persisted AI coaching report
  coachGame: (gameId: string): Promise<CoachingResponse> =>
    request<CoachingResponse>(`/games/${encodeURIComponent(gameId)}/coach`, {
      method: "POST",
    }),
};

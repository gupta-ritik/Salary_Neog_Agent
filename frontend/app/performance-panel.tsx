"use client";

import { useState } from "react";
import { api, type PerformanceMetrics } from "@/lib/api";

function ms(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(2)} ms`;
}

export default function PerformancePanel() {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMetrics() {
    setLoading(true);
    setError("");
    try {
      setMetrics(await api.getPerformance());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load performance metrics.");
    } finally {
      setLoading(false);
    }
  }

  const latency = metrics?.api_latency ?? {};
  const metric = (path: string, cache: "hit" | "miss") => latency[`${path}|${cache}`];

  return (
    <section className="space-y-4 rounded-2xl border border-white bg-white/80 p-4 sm:p-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-violet-600">Engineering telemetry</p>
          <h2 className="mt-1 text-lg font-bold">Performance comparison</h2>
          <p className="mt-1 text-sm text-violet-600">Measure coach report reuse and Redis hit/miss latency in this backend process.</p>
        </div>
        <button onClick={loadMetrics} disabled={loading} className="rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold hover:bg-white0 disabled:opacity-50">
          {loading ? "Loading…" : "Refresh metrics"}
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {metrics && <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric label="Reports generated" value={metrics.coaching.reports_generated} />
          <Metric label="Saved reports reused" value={metrics.coaching.saved_reports_reused} />
          <Metric label="Estimated LLM calls avoided" value={metrics.coaching.estimated_llm_calls_avoided} />
          <Metric label="Report reuse rate" value={`${metrics.coaching.reuse_rate_percent}%`} />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <LatencyCard title="GET /games" hit={metric("/games", "hit")} miss={metric("/games", "miss")} />
          <LatencyCard title="GET /stats" hit={metric("/stats", "hit")} miss={metric("/stats", "miss")} />
        </div>
        <div className="rounded-xl border border-violet-200 p-3 text-sm">
          <p className="font-semibold">AI coaching generation latency</p>
          <p className="mt-1 text-violet-800">Average: {ms(metrics.coaching.avg_generation_latency_ms)}</p>
          <p className="mt-1 text-xs text-violet-600">Redis cache hits: {metrics.redis.cache_hits} · Misses: {metrics.redis.cache_misses}</p>
        </div>
        <p className="text-xs leading-5 text-violet-600">{metrics.scope}. Generate a few requests, then refresh. For a fair comparison, trigger a cache miss, repeat the same GET within its TTL for a hit, and compare averages over multiple samples. These are application-level measurements, not a controlled benchmark.</p>
      </>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-xl border border-violet-200 bg-white/80 p-3"><p className="text-xs text-violet-600">{label}</p><p className="mt-1 text-xl font-bold">{value}</p></div>;
}

function LatencyCard({ title, hit, miss }: { title: string; hit?: PerformanceMetrics["api_latency"][string]; miss?: PerformanceMetrics["api_latency"][string] }) {
  const saved = hit && miss && miss.avg_ms > 0 ? ((miss.avg_ms - hit.avg_ms) / miss.avg_ms) * 100 : null;
  return <div className="rounded-xl border border-violet-200 p-3"><p className="font-semibold">{title}</p><div className="mt-3 grid grid-cols-2 gap-2"><div><p className="text-xs text-violet-600">Cache hit avg</p><p className="font-semibold">{ms(hit?.avg_ms)}</p><p className="text-xs text-violet-600">n={hit?.count ?? 0}</p></div><div><p className="text-xs text-violet-600">Cache miss avg</p><p className="font-semibold">{ms(miss?.avg_ms)}</p><p className="text-xs text-violet-600">n={miss?.count ?? 0}</p></div></div><p className="mt-3 text-xs text-violet-600">Observed latency reduction: {saved == null ? "need both hit and miss samples" : `${saved.toFixed(1)}%`}</p></div>;
}

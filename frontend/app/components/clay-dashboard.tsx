"use client";

import { useState } from "react";

type Metric = {
  label: string;
  value: string;
  description: string;
};

const metrics: Metric[] = [
  {
    label: "Final Offer",
    value: "—",
    description: "Your latest negotiation result",
  },
  {
    label: "Coach Latency",
    value: "—",
    description: "Average feedback generation time",
  },
  {
    label: "Cache Hit Rate",
    value: "—",
    description: "Responses served from cache",
  },
];

export default function ClayDashboard() {
  const [question, setQuestion] = useState("");

  return (
    <main className="clay-app">
      <div className="clay-container">
        <header className="clay-header">
          <div>
            <h1 className="clay-title">
              Salary Negotiation Agent
            </h1>
            <p className="clay-subtitle">
              Practice negotiation, improve your strategy,
              and measure your performance.
            </p>
          </div>

          <button
            type="button"
            className="clay-button"
            onClick={() => {
              document
                .getElementById("negotiation-chat")
                ?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            Start Negotiating
          </button>
        </header>

        <section
          className="clay-grid"
          aria-label="Negotiation dashboard"
        >
          {metrics.map((metric) => (
            <article
              key={metric.label}
              className="clay-col-4"
            >
              <div className="clay-metric">
                <p className="clay-muted">{metric.label}</p>
                <div className="clay-metric-value">
                  {metric.value}
                </div>
                <p className="clay-muted">
                  {metric.description}
                </p>
              </div>
            </article>
          ))}

          <article className="clay-col-8">
            <section
              id="negotiation-chat"
              className="clay-card"
            >
              <h2>Negotiation Chat</h2>
              <p className="clay-muted">
                Your existing recruiter messages and
                responses should render here.
              </p>

              <div className="clay-chat-history">
                <div className="clay-message clay-message-recruiter">
                  Welcome! What salary are you targeting?
                </div>

                {question.trim() && (
                  <div className="clay-message clay-message-user">
                    {question}
                  </div>
                )}
              </div>

              <form
                className="clay-form"
                onSubmit={(event) => {
                  event.preventDefault();

                  // Connect this handler to your existing
                  // message-sending API function.
                  if (!question.trim()) return;

                  console.log("Connect to existing API:", question);
                }}
              >
                <input
                  className="clay-input"
                  aria-label="Negotiation message"
                  placeholder="Enter your salary expectation..."
                  value={question}
                  onChange={(event) =>
                    setQuestion(event.target.value)
                  }
                />

                <button
                  type="submit"
                  className="clay-button"
                  disabled={!question.trim()}
                >
                  Send
                </button>
              </form>
            </section>
          </article>

          <article className="clay-col-4">
            <section className="clay-card clay-card-mint">
              <h2>AI Negotiation Coach</h2>
              <p>
                Review negotiation tactics, strengths,
                and areas for improvement.
              </p>

              <ul>
                <li>Anchoring strategy</li>
                <li>Evidence-based salary justification</li>
                <li>Communication effectiveness</li>
              </ul>

              <p className="clay-muted">
                Connect this panel to your existing coaching
                endpoint and display its real response.
              </p>
            </section>

            <div style={{ height: 16 }} />

            <section className="clay-card clay-card-peach">
              <h2>Performance</h2>
              <p>
                Compare cached and uncached API latency,
                coach response time, and LLM calls avoided.
              </p>
              <p className="clay-muted">
                Populate these values using your existing
                performance metrics endpoint.
              </p>
            </section>
          </article>
        </section>
      </div>
    </main>
  );
}
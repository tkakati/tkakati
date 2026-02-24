"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SignOutButton } from "@clerk/nextjs";

import type {
  CollectorRunRequest,
  CollectorRunResponse,
  HiringStrictness,
  PaginatedPosts,
  PaginatedSignals,
  PostStatus,
  Run,
  SignalMetrics,
} from "@/lib/types";
import { POST_STATUSES } from "@/lib/types";

type Props = {
  initialPosts?: PaginatedPosts;
  initialRuns?: Run[];
};

const DEFAULT_DESIGNATIONS =
  "product manager, senior product manager, product marketing manager, program manager";

export default function Dashboard({ initialPosts, initialRuns }: Props) {
  const [posts, setPosts] = useState<PaginatedPosts>(
    initialPosts ?? { items: [], page: 1, page_size: 25, total: 0 },
  );
  const [runs, setRuns] = useState<Run[]>(initialRuns ?? []);
  const [signals, setSignals] = useState<PaginatedSignals>({
    items: [],
    page: 1,
    page_size: 25,
    total: 0,
    total_base: 0,
  });
  const [metrics, setMetrics] = useState<SignalMetrics>({
    strong_signals: 0,
    medium_confidence: 0,
    filtered: 0,
    common_filter_reasons: [],
    false_positive_trends: [],
    emerging_companies: [],
    hidden_hiring_clusters: [],
  });

  const [company, setCompany] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [desiredDesignations, setDesiredDesignations] = useState(DEFAULT_DESIGNATIONS);
  const [desiredLocations, setDesiredLocations] = useState("United States");
  const [lastDays, setLastDays] = useState("7");

  const [page, setPage] = useState(initialPosts?.page ?? 1);
  const [signalPage, setSignalPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [updatingPostId, setUpdatingPostId] = useState<number | null>(null);
  const [runResult, setRunResult] = useState<CollectorRunResponse | null>(null);

  const [minConfidence, setMinConfidence] = useState(0.6);
  const [hiringStrictness, setHiringStrictness] = useState<HiringStrictness>("medium");
  const [roleSimilarityThreshold, setRoleSimilarityThreshold] = useState(0.4);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(posts.total / posts.page_size)), [posts]);
  const signalPages = useMemo(() => Math.max(1, Math.ceil(signals.total / signals.page_size)), [signals]);

  async function refreshPosts(nextPage = 1) {
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo).toISOString());
    params.set("page", String(nextPage));

    const response = await fetch(`/api/posts?${params.toString()}`, { cache: "no-store" });
    const data = (await response.json()) as PaginatedPosts;
    setPosts(data);
    setPage(nextPage);
  }

  async function refreshRuns() {
    const response = await fetch("/api/runs", { cache: "no-store" });
    const data = (await response.json()) as Run[];
    setRuns(data);
  }

  async function refreshSignals(nextPage = 1) {
    const params = new URLSearchParams();
    params.set("min_confidence", String(minConfidence));
    params.set("hiring_strictness", hiringStrictness);
    params.set("role_similarity_threshold", String(roleSimilarityThreshold));
    params.set("last_days", String(Number(lastDays) > 0 ? Number(lastDays) : 7));
    params.set("page", String(nextPage));
    params.set("page_size", "20");

    const response = await fetch(`/api/signals?${params.toString()}`, { cache: "no-store" });
    const data = (await response.json()) as PaginatedSignals;
    setSignals(data);
    setSignalPage(nextPage);
  }

  async function refreshSignalMetrics() {
    const params = new URLSearchParams();
    params.set("min_confidence", String(minConfidence));
    params.set("hiring_strictness", hiringStrictness);
    params.set("role_similarity_threshold", String(roleSimilarityThreshold));
    params.set("last_days", String(Number(lastDays) > 0 ? Number(lastDays) : 7));
    const response = await fetch(`/api/signals/analytics?${params.toString()}`, { cache: "no-store" });
    const data = (await response.json()) as SignalMetrics;
    setMetrics(data);
  }

  useEffect(() => {
    setLoading(true);
    void Promise.all([refreshPosts(1), refreshRuns(), refreshSignals(1), refreshSignalMetrics()]).finally(() =>
      setLoading(false),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void Promise.all([refreshSignals(1), refreshSignalMetrics()]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minConfidence, hiringStrictness, roleSimilarityThreshold, lastDays]);

  async function runCollectorNow() {
    setLoading(true);
    const payload: CollectorRunRequest = {
      designations: desiredDesignations
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      locations: desiredLocations
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean),
      last_days: Number(lastDays) > 0 ? Number(lastDays) : 7,
    };
    const response = await fetch("/api/collector/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = (await response.json()) as CollectorRunResponse;
    setRunResult(data);
    await Promise.all([refreshPosts(1), refreshRuns(), refreshSignals(1), refreshSignalMetrics()]);
    setLoading(false);
  }

  async function clearFilters() {
    setCompany("");
    setDateFrom("");
    setDateTo("");
    await refreshPosts(1);
  }

  async function updateStatus(postId: number, status: PostStatus) {
    setUpdatingPostId(postId);
    const response = await fetch(`/api/posts/${postId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });

    if (response.ok) {
      setPosts((prev) => ({
        ...prev,
        items: prev.items.map((item) => (item.id === postId ? { ...item, status } : item)),
      }));
    }
    setUpdatingPostId(null);
  }

  const csvHref = useMemo(() => {
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo).toISOString());
    return `/api/export?${params.toString()}`;
  }, [company, dateFrom, dateTo]);

  return (
    <main className="container">
      <header className="header-row">
        <div>
          <h1>Hiring Intelligence Dashboard</h1>
          <p className="subtle">Explainable signal scoring, precision tuning, and analyst review workflow.</p>
        </div>
        <div className="action-row">
          <Link href="/review" className="btn-link">
            Review queue
          </Link>
          <SignOutButton>
            <button>Logout</button>
          </SignOutButton>
        </div>
      </header>

      <section className="panel">
        <h2>Collector</h2>
        <div className="filters">
          <input
            placeholder="Desired designations (comma-separated)"
            value={desiredDesignations}
            onChange={(e) => setDesiredDesignations(e.target.value)}
          />
          <input
            placeholder="Desired locations (comma-separated)"
            value={desiredLocations}
            onChange={(e) => setDesiredLocations(e.target.value)}
          />
          <input
            type="number"
            min={1}
            max={60}
            value={lastDays}
            onChange={(e) => setLastDays(e.target.value)}
            placeholder="Last days"
          />
          <button onClick={() => void runCollectorNow()} disabled={loading}>
            Run collector now
          </button>
        </div>
      </section>

      {runResult ? (
        <p className="run-result">
          Last run: {runResult.status} (inserted {runResult.inserted}, skipped {runResult.skipped})
        </p>
      ) : null}

      <section className="panel">
        <h2>Precision tuning</h2>
        <div className="tuning-grid">
          <label>
            Minimum confidence: <strong>{minConfidence.toFixed(2)}</strong>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
            />
          </label>
          <label>
            Hiring strictness
            <select value={hiringStrictness} onChange={(e) => setHiringStrictness(e.target.value as HiringStrictness)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label>
            Role similarity threshold: <strong>{roleSimilarityThreshold.toFixed(2)}</strong>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={roleSimilarityThreshold}
              onChange={(e) => setRoleSimilarityThreshold(Number(e.target.value))}
            />
          </label>
        </div>
      </section>

      <section className="cards-grid">
        <article className="metric-card">
          <h3>Strong signals</h3>
          <p>{metrics.strong_signals}</p>
        </article>
        <article className="metric-card">
          <h3>Medium confidence</h3>
          <p>{metrics.medium_confidence}</p>
        </article>
        <article className="metric-card">
          <h3>Filtered</h3>
          <p>{metrics.filtered}</p>
        </article>
      </section>

      <section className="panel">
        <h2>Signal explainability</h2>
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Role</th>
              <th>Strength</th>
              <th>Confidence</th>
              <th>Company source</th>
              <th>Hiring confidence</th>
              <th>Role match</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {signals.items.map((signal) => (
              <tr key={signal.id}>
                <td>{signal.company ?? "Unknown"}</td>
                <td>{signal.role ?? "-"}</td>
                <td>{signal.signal_strength}</td>
                <td>{signal.confidence.toFixed(2)}</td>
                <td>{normalizeSource(signal.company_source)}</td>
                <td>{signal.hiring_confidence.toFixed(2)}</td>
                <td>{signal.role_match_score.toFixed(2)}</td>
                <td>
                  <a href={signal.source_url} target="_blank" rel="noreferrer">
                    ↗
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pagination-row">
          <button disabled={signalPage <= 1 || loading} onClick={() => void refreshSignals(signalPage - 1)}>
            Prev
          </button>
          <span>
            Page {signalPage} / {signalPages}
          </span>
          <button disabled={signalPage >= signalPages || loading} onClick={() => void refreshSignals(signalPage + 1)}>
            Next
          </button>
        </div>
      </section>

      <section className="panel split">
        <div>
          <h2>Noise analytics</h2>
          <ul className="list">
            {metrics.common_filter_reasons.map((item) => (
              <li key={item.reason}>
                <span>{item.reason.replaceAll("_", " ")}</span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
          <h3>False positive trends</h3>
          <ul className="list">
            {metrics.false_positive_trends.length === 0 ? <li>No rejected signals yet</li> : null}
            {metrics.false_positive_trends.map((item) => (
              <li key={item.day}>
                <span>{new Date(item.day).toLocaleDateString("en-US")}</span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h2>Company discovery</h2>
          <h3>Emerging companies</h3>
          <ul className="list">
            {metrics.emerging_companies.map((item) => (
              <li key={item.company}>
                <span>
                  {item.company} ({item.signals} signals)
                </span>
                <strong>{item.avg_strength.toFixed(2)}</strong>
              </li>
            ))}
          </ul>
          <h3>Hidden hiring clusters</h3>
          <ul className="list">
            {metrics.hidden_hiring_clusters.map((item) => (
              <li key={`${item.company}-${item.role}`}>
                <span>
                  {item.company} · {item.role}
                </span>
                <strong>{item.signals}</strong>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="panel">
        <h2>Table Filters</h2>
        <div className="filters">
          <input placeholder="Filter by company" value={company} onChange={(e) => setCompany(e.target.value)} />
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <button onClick={() => void refreshPosts(1)} disabled={loading}>
            Apply filters
          </button>
          <button onClick={() => void clearFilters()} disabled={loading}>
            Clear filters
          </button>
          <a href={csvHref}>Download CSV</a>
        </div>
      </section>

      <section>
        <h2>Posts</h2>
        <table>
          <thead>
            <tr>
              <th>First Seen</th>
              <th>Company</th>
              <th>Position</th>
              <th>Link</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {posts.items.map((post) => (
              <tr key={post.id}>
                <td>{new Date(post.first_seen).toLocaleDateString("en-US")}</td>
                <td>{post.company ?? "-"}</td>
                <td>{post.query_used}</td>
                <td>
                  <a href={post.post_url} target="_blank" rel="noreferrer">
                    ↗
                  </a>
                </td>
                <td>
                  <select
                    value={post.status}
                    disabled={updatingPostId === post.id}
                    onChange={(e) => void updateStatus(post.id, e.target.value as PostStatus)}
                  >
                    {POST_STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pagination-row">
          <button disabled={page <= 1 || loading} onClick={() => void refreshPosts(page - 1)}>
            Prev
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button disabled={page >= totalPages || loading} onClick={() => void refreshPosts(page + 1)}>
            Next
          </button>
        </div>
      </section>

      <section>
        <h2>Run History</h2>
        <div className="runs-panel">
          {runs.map((run) => (
            <div key={run.id} className="run-card">
              <div>Run #{run.id}</div>
              <div>Status: {run.status}</div>
              <div>Inserted: {run.inserted}</div>
              <div>Skipped: {run.skipped}</div>
              <div>Started: {new Date(run.started_at).toLocaleString()}</div>
              {run.error ? <div className="error">Error: {run.error}</div> : null}
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function normalizeSource(source: string): string {
  if (source === "llm") return "LLM";
  if (source === "url") return "URL";
  if (source === "domain" || source === "regex") return "Snippet";
  return source || "-";
}

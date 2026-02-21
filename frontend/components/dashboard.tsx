"use client";

import { useEffect, useMemo, useState } from "react";
import { SignOutButton } from "@clerk/nextjs";
import type { CollectorRunRequest, CollectorRunResponse, PaginatedPosts, PostStatus, Run } from "@/lib/types";
import { POST_STATUSES } from "@/lib/types";

type Props = {
  initialPosts?: PaginatedPosts;
  initialRuns?: Run[];
};

export default function Dashboard({ initialPosts, initialRuns }: Props) {
  const [posts, setPosts] = useState<PaginatedPosts>(
    initialPosts ?? { items: [], page: 1, page_size: 25, total: 0 },
  );
  const [runs, setRuns] = useState<Run[]>(initialRuns ?? []);
  const [company, setCompany] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [desiredDesignations, setDesiredDesignations] = useState(
    "product manager, senior product manager, product marketing manager, program manager",
  );
  const [desiredLocations, setDesiredLocations] = useState("United States");
  const [lastDays, setLastDays] = useState("7");
  const [page, setPage] = useState(initialPosts?.page ?? 1);
  const [loading, setLoading] = useState(false);
  const [updatingPostId, setUpdatingPostId] = useState<number | null>(null);
  const [runResult, setRunResult] = useState<CollectorRunResponse | null>(null);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(posts.total / posts.page_size)), [posts]);

  async function refreshPosts(nextPage = 1) {
    setLoading(true);
    const params = new URLSearchParams();
    if (company) params.set("company", company);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo).toISOString());
    params.set("page", String(nextPage));

    const response = await fetch(`/api/posts?${params.toString()}`, { cache: "no-store" });
    const data = (await response.json()) as PaginatedPosts;
    setPosts(data);
    setPage(nextPage);
    setLoading(false);
  }

  async function refreshRuns() {
    const response = await fetch("/api/runs", { cache: "no-store" });
    const data = (await response.json()) as Run[];
    setRuns(data);
  }

  useEffect(() => {
    void Promise.all([refreshPosts(1), refreshRuns()]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    await Promise.all([refreshPosts(1), refreshRuns()]);
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
        <h1>Hiring Post Collector</h1>
        <div className="action-row">
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
            max={30}
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

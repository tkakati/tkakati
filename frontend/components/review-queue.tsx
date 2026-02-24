"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { ReviewAction, Signal } from "@/lib/types";

export default function ReviewQueue() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [labelDraft, setLabelDraft] = useState<Record<number, string>>({});
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});

  async function refreshQueue() {
    const response = await fetch("/api/signals/review-queue?limit=200", { cache: "no-store" });
    const data = (await response.json()) as Signal[];
    setSignals(data);
  }

  useEffect(() => {
    void refreshQueue();
  }, []);

  async function reviewSignal(signalId: number, action: ReviewAction) {
    setActiveId(signalId);
    const body = {
      action,
      label: labelDraft[signalId] || undefined,
      notes: notesDraft[signalId] || undefined,
    };
    const response = await fetch(`/api/signals/${signalId}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.ok) {
      setSignals((prev) => prev.filter((item) => item.id !== signalId));
    }
    setActiveId(null);
  }

  return (
    <main className="container">
      <header className="header-row">
        <div>
          <h1>Review queue</h1>
          <p className="subtle">Approve, reject, or relabel pending signals for model tuning feedback.</p>
        </div>
        <Link href="/" className="btn-link">
          Back to dashboard
        </Link>
      </header>

      <section className="panel">
        <h2>Pending signals ({signals.length})</h2>
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Role</th>
              <th>Strength</th>
              <th>Confidence</th>
              <th>Reasoning</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.id}>
                <td>{signal.company ?? "Unknown"}</td>
                <td>{signal.role ?? "-"}</td>
                <td>{signal.signal_strength}</td>
                <td>{signal.confidence.toFixed(2)}</td>
                <td>{signal.reasoning ?? "-"}</td>
                <td>
                  <div className="review-actions">
                    <input
                      placeholder="Relabel"
                      value={labelDraft[signal.id] ?? ""}
                      onChange={(e) =>
                        setLabelDraft((prev) => ({
                          ...prev,
                          [signal.id]: e.target.value,
                        }))
                      }
                    />
                    <input
                      placeholder="Notes"
                      value={notesDraft[signal.id] ?? ""}
                      onChange={(e) =>
                        setNotesDraft((prev) => ({
                          ...prev,
                          [signal.id]: e.target.value,
                        }))
                      }
                    />
                    <div className="action-row">
                      <button disabled={activeId === signal.id} onClick={() => void reviewSignal(signal.id, "approve")}>
                        Approve
                      </button>
                      <button disabled={activeId === signal.id} onClick={() => void reviewSignal(signal.id, "reject")}>
                        Reject
                      </button>
                      <button disabled={activeId === signal.id} onClick={() => void reviewSignal(signal.id, "relabel")}>
                        Relabel
                      </button>
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}

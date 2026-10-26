"use client";

// Threads that went to Buffer (or were dry-run), from the backend's SQLite
// record via this app's own /api/threads proxy. Refetches whenever the live
// thread's publish status changes, so a new send shows up without a reload.

import { useEffect, useState } from "react";

import { formatDue, useThreadState } from "./ThreadBoard";

type SentThread = {
  id: number;
  posts: string[];
  status: string;
  due_at?: string;
  created_at: string;
};

const LABEL: Record<string, string> = {
  dry_run: "Dry run",
  scheduled: "Scheduled",
  queued: "Queued",
};

export function ThreadHistory() {
  const status = useThreadState().thread_status;
  const [threads, setThreads] = useState<SentThread[]>([]);

  useEffect(() => {
    fetch("/api/threads")
      .then((r) => (r.ok ? r.json() : { threads: [] }))
      .then((d) => setThreads(d.threads ?? []))
      .catch(() => setThreads([]));
  }, [status]);

  return (
    <section className="card">
      <h2>Sent threads</h2>
      {threads.length === 0 ? (
        <p className="muted">Nothing sent yet. Approved threads land here.</p>
      ) : (
        <ul className="history">
          {threads.map((t) => (
            <li key={t.id}>
              <details>
                <summary>
                  <span className={`chip ${t.status === "dry_run" ? "chip-dry" : "chip-scheduled"}`}>
                    {LABEL[t.status] ?? t.status}
                  </span>
                  <span className="history-hook">{t.posts[0]}</span>
                  <span className="muted">
                    {t.posts.length} posts{t.due_at ? ` · ${formatDue(t.due_at)}` : ""}
                  </span>
                </summary>
                <ol>
                  {t.posts.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ol>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

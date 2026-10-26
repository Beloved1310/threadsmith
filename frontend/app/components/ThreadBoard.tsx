"use client";

// The thread being worked on, straight from the backend's shared state.
// tools.save_thread writes state["thread"] as structured posts (text, length,
// within_limit), so nothing here parses the chat: the cards ARE the draft
// publish_thread will send. Quick-edit buttons send an ordinary chat message,
// so every revision still goes through thread_writer and save_thread.

import { useCoAgent, useCopilotChatInternal } from "@copilotkit/react-core";

export const X_LIMIT = 280;

export type ThreadPost = {
  index: number;
  text: string;
  length: number;
  within_limit: boolean;
  over_by: number;
};

export type ThreadState = {
  pipeline_stage?: string;
  thread?: ThreadPost[];
  thread_ok?: boolean;
  thread_status?: string;
  thread_due_at?: string;
};

const QUICK_EDITS = [
  { label: "Punchier", ask: "make it punchier and more concrete" },
  { label: "Shorter", ask: "cut it to under 200 characters" },
  { label: "Rewrite", ask: "rewrite it with a different angle" },
];

export function useThreadState() {
  return useCoAgent<ThreadState>({ name: "thread_smith" }).state ?? {};
}

export function formatDue(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

/** Ring that fills toward 280 and turns red past it, like X's composer. */
function CharRing({ length }: { length: number }) {
  const r = 9;
  const c = 2 * Math.PI * r;
  const ratio = Math.min(length / X_LIMIT, 1);
  const tone = length > X_LIMIT ? "over" : length > 250 ? "near" : "ok";
  return (
    <span className={`char-ring ${tone}`} title={`${length} / ${X_LIMIT} characters`}>
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
        <circle cx="11" cy="11" r={r} className="ring-track" />
        <circle
          cx="11"
          cy="11"
          r={r}
          className="ring-fill"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - ratio)}
        />
      </svg>
      <span className="char-count">{length > 250 ? X_LIMIT - length : length}</span>
    </span>
  );
}

function StatusChip({ state }: { state: ThreadState }) {
  const status = state.thread_status ?? "draft";
  if (status === "scheduled")
    return <span className="chip chip-scheduled">Scheduled in Buffer · {formatDue(state.thread_due_at)}</span>;
  if (status === "queued") return <span className="chip chip-scheduled">In Buffer queue</span>;
  if (status === "dry_run") return <span className="chip chip-dry">Dry run · nothing sent</span>;
  return <span className="chip">Draft</span>;
}

function EmptyBoard() {
  return (
    <div className="thread-empty">
      {[0, 1, 2].map((i) => (
        <div key={i} className="tweet tweet-skeleton" aria-hidden="true">
          <div className="tweet-avatar" />
          <div className="tweet-body">
            <span className="skeleton-line" style={{ width: `${80 - i * 15}%` }} />
            <span className="skeleton-line" style={{ width: `${60 - i * 10}%` }} />
          </div>
        </div>
      ))}
      <p>
        Give the chat an idea or paste a link. The thread appears here post by
        post, with every character counted.
      </p>
    </div>
  );
}

export function ThreadBoard() {
  const state = useThreadState();
  const { sendMessage, isLoading } = useCopilotChatInternal();
  const posts = state.thread ?? [];
  const over = posts.filter((p) => !p.within_limit).length;

  const revise = (index: number, ask: string) =>
    sendMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: `Revise post ${index}: ${ask}. Keep every other post exactly as it is.`,
    });

  return (
    <section className="card board">
      <div className="board-head">
        <h2>Thread</h2>
        {posts.length > 0 && (
          <>
            <span className="board-meta">
              {posts.length} posts ·{" "}
              {over ? <b className="bad">{over} over {X_LIMIT}</b> : "all within limit"}
            </span>
            <StatusChip state={state} />
          </>
        )}
      </div>

      {posts.length === 0 ? (
        <EmptyBoard />
      ) : (
        <ol className="thread">
          {posts.map((post) => (
            <li key={post.index} className={`tweet ${post.within_limit ? "" : "tweet-over"}`}>
              <div className="tweet-rail">
                <div className="tweet-avatar">{post.index}</div>
                {post.index < posts.length && <span className="tweet-line" />}
              </div>
              <div className="tweet-body">
                <div className="tweet-head">
                  <span className="tweet-name">You</span>
                  <span className="tweet-pos">
                    {post.index}/{posts.length}
                  </span>
                </div>
                <p className="tweet-text">{post.text}</p>
                <div className="tweet-foot">
                  <div className="quick-edits">
                    {QUICK_EDITS.map((q) => (
                      <button
                        key={q.label}
                        disabled={isLoading}
                        onClick={() => revise(post.index, q.ask)}
                      >
                        {q.label}
                      </button>
                    ))}
                  </div>
                  <CharRing length={post.length} />
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

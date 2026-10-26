"use client";

import { useThreadState } from "./ThreadBoard";

const STAGES: { key: string; label: string }[] = [
  { key: "idea", label: "Idea" },
  { key: "researching", label: "Research" },
  { key: "drafting", label: "Write" },
  { key: "awaiting_approval", label: "Approve" },
  { key: "sent", label: "Buffer" },
];

// publish_thread's three outcomes all land on the last step; the label says which.
const SENT_LABEL: Record<string, string> = {
  dry_run: "Dry run",
  scheduled: "Scheduled",
  queued: "Queued",
};

/** Horizontal stepper mirroring the backend's pipeline_stage shared state. */
export function StagePanel() {
  const stage = useThreadState().pipeline_stage ?? "idea";
  const current = stage in SENT_LABEL ? "sent" : stage;
  const currentIdx = Math.max(0, STAGES.findIndex((s) => s.key === current));

  return (
    <ol className="stepper" aria-label="Pipeline">
      {STAGES.map((s, i) => {
        const status = i < currentIdx ? "done" : i === currentIdx ? "current" : "";
        const label = s.key === "sent" && SENT_LABEL[stage] ? SENT_LABEL[stage] : s.label;
        return (
          <li key={s.key} className={`step ${status}`}>
            <span className="dot">{i < currentIdx ? "✓" : i + 1}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

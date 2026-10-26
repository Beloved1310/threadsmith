"use client";

// Renders ADK's framework-level approval gate (FunctionTool(require_confirmation=True)
// on publish_thread) in the chat. ADK synthesizes a call named
// "adk_request_confirmation" carrying { originalFunctionCall, toolConfirmation };
// nothing resolves the pending call unless the frontend answers it.
//
// publish_thread takes no arguments (it sends the saved thread), so the card
// shows that thread from shared state instead of the call's args.

import { useCopilotAction } from "@copilotkit/react-core";

import { useThreadState, X_LIMIT } from "./ThreadBoard";

function ThreadPreview() {
  const posts = useThreadState().thread ?? [];
  if (!posts.length) return null;
  return (
    <ol className="confirm-thread">
      {posts.map((p) => (
        <li key={p.index} className={p.within_limit ? "" : "bad"}>
          <span>{p.text}</span>
          <small>
            {p.length}/{X_LIMIT}
          </small>
        </li>
      ))}
    </ol>
  );
}

export function ConfirmAction() {
  useCopilotAction(
    {
      name: "adk_request_confirmation",
      description: "Approve or reject a pending tool call before it runs.",
      parameters: [
        { name: "originalFunctionCall", type: "object", attributes: [] },
        { name: "toolConfirmation", type: "object", attributes: [] },
      ],
      renderAndWaitForResponse: ({ args, status, respond }) => {
        const call = (args as any)?.originalFunctionCall ?? {};
        const isThread = call?.name === "publish_thread";

        if (status === "complete") {
          return <p className="confirm-done">Responded.</p>;
        }

        return (
          <div className="confirm-card">
            <p>
              <strong>
                {isThread ? "Send this thread to X via Buffer?" : `Approve ${call?.name ?? "this action"}?`}
              </strong>
            </p>
            {isThread ? (
              <ThreadPreview />
            ) : (
              <pre>{JSON.stringify(call?.args ?? {}, null, 2)}</pre>
            )}
            <div className="confirm-buttons">
              <button
                className="confirm-approve"
                disabled={status !== "executing"}
                onClick={() => respond?.({ confirmed: true })}
              >
                Approve
              </button>
              <button
                className="confirm-reject"
                disabled={status !== "executing"}
                onClick={() => respond?.({ confirmed: false })}
              >
                Reject
              </button>
            </div>
          </div>
        );
      },
    },
    [],
  );

  return null;
}

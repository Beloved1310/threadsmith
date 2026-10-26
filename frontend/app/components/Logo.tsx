// ThreadSmith mark: three stitched posts on a thread.
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo">
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <path d="M10 8v16" stroke="var(--accent-ink)" strokeWidth="2" strokeLinecap="round" strokeDasharray="2 3.2" />
      <circle cx="10" cy="8" r="2.6" fill="var(--accent-ink)" />
      <circle cx="10" cy="16" r="2.6" fill="var(--accent-ink)" />
      <circle cx="10" cy="24" r="2.6" fill="var(--accent-ink)" />
      <path d="M15 8h8M15 16h6M15 24h8" stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

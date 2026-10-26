import { backendFetch } from "@/app/lib/backend";

// Proxies the sent-threads list so the browser stays same-origin.
export const dynamic = "force-dynamic";

export async function GET() {
  const upstream = await backendFetch("/api/threads");
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}

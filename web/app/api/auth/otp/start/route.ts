import { API, forwardHeaders } from "@/lib/session";

export async function POST(request: Request) {
  const res = await fetch(`${API}/v1/auth/otp/start`, { method: "POST", headers: forwardHeaders(request),
    body: await request.text(), cache: "no-store" });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}

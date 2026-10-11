import { NextResponse } from "next/server";
import { API, isHttps, publicOrigin } from "@/lib/session";

// Starts Google or GitHub sign-in. The state value is kept in a short-lived cookie and checked on return.
export async function GET(request: Request, { params }: RouteContext<"/api/auth/oauth/[provider]">) {
  const { provider } = await params;
  const origin = publicOrigin(request);
  const next = new URL(request.url).searchParams.get("next") ?? "";
  const state = crypto.randomUUID();
  const res = await fetch(`${API}/v1/auth/oauth/${provider}/url`, {
    method: "POST", headers: { "content-type": "application/json" }, cache: "no-store",
    body: JSON.stringify({ state, redirect_uri: `${origin}/api/auth/callback/${provider}` }),
  });
  if (!res.ok) {
    const { detail } = await res.json().catch(() => ({ detail: "Sign-in isn't available." }));
    return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(detail)}`, origin));
  }
  const out = NextResponse.redirect((await res.json()).url);
  out.cookies.set({ name: "tw_oauth", value: JSON.stringify({ state, next }), httpOnly: true, sameSite: "lax",
    secure: isHttps(request), path: "/", maxAge: 600 });
  return out;
}

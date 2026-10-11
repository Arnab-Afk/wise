import { NextResponse } from "next/server";
import { API, forwardHeaders, publicOrigin, readCookie, sessionCookie } from "@/lib/session";

export async function GET(request: Request, { params }: RouteContext<"/api/auth/callback/[provider]">) {
  const { provider } = await params;
  const origin = publicOrigin(request);
  const url = new URL(request.url);
  const fail = (msg: string) => {
    const out = NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(msg)}`, origin));
    out.cookies.delete("tw_oauth");
    return out;
  };
  let saved: { state?: string; next?: string } = {};
  try { saved = JSON.parse(readCookie(request, "tw_oauth") ?? "{}"); } catch {}
  if (url.searchParams.get("error")) return fail("Sign-in was cancelled.");
  if (!saved.state || saved.state !== url.searchParams.get("state")) return fail("Sign-in expired. Please try again.");
  const res = await fetch(`${API}/v1/auth/oauth/${provider}/callback`, {
    method: "POST", headers: forwardHeaders(request), cache: "no-store",
    body: JSON.stringify({ code: url.searchParams.get("code"), redirect_uri: `${origin}/api/auth/callback/${provider}` }),
  });
  const data = await res.json();
  if (!res.ok) return fail(data.detail ?? "Sign-in failed.");
  const next = saved.next?.startsWith("/") ? saved.next : data.has_workspace ? "/overview" : "/onboarding";
  const out = NextResponse.redirect(new URL(next, origin));
  out.cookies.set(sessionCookie(request, data.token, data.expires_days));
  out.cookies.delete("tw_oauth");
  return out;
}

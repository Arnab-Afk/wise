import { NextResponse } from "next/server";
import { API, forwardHeaders, sessionCookie } from "@/lib/session";

export async function POST(request: Request) {
  const res = await fetch(`${API}/v1/auth/otp/verify`, { method: "POST", headers: forwardHeaders(request),
    body: await request.text(), cache: "no-store" });
  const data = await res.json();
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  const out = NextResponse.json({ new_user: data.new_user, has_workspace: data.has_workspace, user: data.user });
  out.cookies.set(sessionCookie(request, data.token, data.expires_days));
  return out;
}

import { NextResponse } from "next/server";
import { API, COOKIE, forwardHeaders, publicOrigin, readCookie } from "@/lib/session";

export async function POST(request: Request) {
  await fetch(`${API}/v1/auth/logout`, { method: "POST", headers: forwardHeaders(request, readCookie(request, COOKIE)) }).catch(() => {});
  const out = NextResponse.redirect(new URL("/login", publicOrigin(request)), 303);
  out.cookies.delete(COOKIE);
  return out;
}

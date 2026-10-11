import { NextResponse, type NextRequest } from "next/server";

// Optimistic check only: no session cookie means sign in first. The API checks the session for real.
export function proxy(request: NextRequest) {
  if (request.cookies.has("tw_session")) return NextResponse.next();
  const login = new URL("/login", request.url);
  const next = request.nextUrl.pathname + request.nextUrl.search;
  if (next !== "/") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!login|invite|api|_next|favicon.ico|.*\\..*).*)"],
};

// Server-only helpers for the session cookie. The API never sees the cookie itself; the web app
// forwards it as a bearer token.
export const API = process.env.TRACEWISE_API_URL ?? "http://localhost:19100";
export const COOKIE = "tw_session";
const DAY = 60 * 60 * 24;

export function isHttps(request: Request) {
  return request.headers.get("x-forwarded-proto") === "https" || new URL(request.url).protocol === "https:";
}

export function publicOrigin(request: Request) {
  const h = request.headers;
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? new URL(request.url).host;
  return `${isHttps(request) ? "https" : "http"}://${host}`;
}

export function sessionCookie(request: Request, token: string, days = 30) {
  return { name: COOKIE, value: token, httpOnly: true, sameSite: "lax" as const, secure: isHttps(request),
    path: "/", maxAge: days * DAY };
}

/** Headers to forward to the API: who the user is, and where they came from (for sign-in alerts). */
export function forwardHeaders(request: Request, token?: string | null) {
  const h: Record<string, string> = { "content-type": "application/json" };
  const ua = request.headers.get("user-agent");
  const ip = request.headers.get("cf-connecting-ip") ?? request.headers.get("x-forwarded-for")?.split(",")[0];
  if (ua) h["user-agent"] = ua;
  if (ip) h["x-forwarded-for"] = ip;
  if (token) h.authorization = `Bearer ${token}`;
  const ws = request.headers.get("x-tracewise-workspace");
  if (ws) h["x-tracewise-workspace"] = ws;
  return h;
}

export function readCookie(request: Request, name: string) {
  const raw = request.headers.get("cookie") ?? "";
  const m = raw.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

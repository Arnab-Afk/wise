// Proxies the browser to the Tracewise API, so only the web app needs to be reachable.
// Streams the response body through, which keeps the live event stream (SSE) working.
const API = process.env.TRACEWISE_API_URL ?? "http://localhost:19100";

async function proxy(request: Request, { params }: RouteContext<"/api/tw/[...path]">) {
  const { path } = await params;
  const url = new URL(request.url);
  const upstream = await fetch(`${API}/${path.join("/")}${url.search}`, {
    method: request.method,
    headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
    body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
    signal: request.signal,
    cache: "no-store",
  });
  const headers = new Headers({ "content-type": upstream.headers.get("content-type") ?? "application/json" });
  if (headers.get("content-type")?.includes("text/event-stream")) {
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };

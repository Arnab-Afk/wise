export const API = "/api/tw";

export type Status = "open" | "investigating" | "acting" | "fixing" | "verifying" | "resolved" | "escalated";

export interface Signal {
  service: string;
  status: string;
  error_rate: number;
  baseline_error_rate: number | null;
  p95_ms: number | null;
  baseline_p95_ms: number | null;
  requests: number;
  sha?: string;
  alerts?: { source: string; kind: string; severity: string; title: string }[];
  error_logs?: number;
}

export interface Incident {
  id: number;
  title: string;
  status: Status;
  severity: string;
  services: string[];
  signals: Signal[];
  summary: string | null;
  root_cause: string | null;
  fix: string | null;
  opened_at: string;
  resolved_at: string | null;
  scenario: string | null;
  turns: number | null;
  cost_usd: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface Step {
  id: number;
  incident_id: number;
  ts: string;
  kind: string;
  phase: string | null;
  title: string;
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface Action {
  id: number;
  kind: string;
  target: string | null;
  params: Record<string, unknown>;
  status: string;
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface IncidentDetail extends Incident {
  steps: Step[];
  actions: Action[];
}

export interface ServiceHealth {
  service: string;
  sha: string;
  requests: number;
  error_rate: number;
  p95_ms: number | null;
  baseline_error_rate: number | null;
  baseline_p95_ms: number | null;
  baseline_requests: number;
  status: string;
  alerts?: { source: string; kind: string; severity: string; title: string }[];
  error_logs?: number;
}

export function currentWorkspace(): string | null {
  try { return localStorage.getItem("tw_workspace"); } catch { return null; }
}

export function currentProject(): string | null {
  try { return localStorage.getItem("tw_project"); } catch { return null; }
}

/** Switch workspace and/or project; everything on screen belongs to the new one, so reload. */
export function switchTo(workspace: number | null, project: number | null) {
  try {
    if (workspace) localStorage.setItem("tw_workspace", String(workspace));
    if (project) localStorage.setItem("tw_project", String(project)); else localStorage.removeItem("tw_project");
  } catch {}
  window.location.assign("/incidents");
}

export function scopeQuery(): string {
  const q = new URLSearchParams();
  const ws = currentWorkspace(), p = currentProject();
  if (ws) q.set("workspace", ws);
  if (p) q.set("project", p);
  return q.toString();
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const ws = currentWorkspace(), project = currentProject();
  const res = await fetch(`${API}${path}`, { cache: "no-store", ...init,
    headers: { "content-type": "application/json", ...(ws ? { "x-tracewise-workspace": ws } : {}),
      ...(project ? { "x-tracewise-project": project } : {}), ...init?.headers } });
  if (typeof window !== "undefined" && (res.status === 401 || res.status === 403)) {
    const body = await res.clone().json().catch(() => ({}));
    const here = location.pathname + location.search;
    if (res.status === 401) location.href = `/login?next=${encodeURIComponent(here)}`;
    else if ((body.code === "no_workspace" || body.code === "no_project") && !location.pathname.startsWith("/onboarding")) location.href = "/onboarding";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const ACTIVE: Status[] = ["open", "investigating", "acting", "fixing", "verifying"];

"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Loader2, Plus, X } from "lucide-react";
import { AuthShell } from "@/components/tw/auth-shell";
import { cn } from "@/lib/utils";

const STEPS = ["Workspace", "Project", "Connect", "Team"];
const STACKS = ["Kubernetes", "Docker", "pm2", "systemd", "VMs", "Serverless", "Postgres", "Redis", "Kafka", "Node.js", "Python", "Go", "Java"];
const ROLES = [["admin", "Admin: people, projects, sources, agents"], ["member", "Member: follow and act on incidents"], ["viewer", "Viewer: read-only"]];

async function call(path: string, method = "GET", body?: unknown) {
  const ws = localStorage.getItem("tw_workspace");
  const r = await fetch(`/api/tw${path}`, { method, body: body ? JSON.stringify(body) : undefined,
    headers: { "content-type": "application/json", ...(ws ? { "x-tracewise-workspace": ws } : {}) } });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) window.location.assign("/login?next=/onboarding");
  if (!r.ok) throw new Error(data.detail ?? "Something went wrong.");
  return data;
}

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
const field = "h-11 w-full rounded-lg border border-black/12 bg-white px-3.5 text-[14px] outline-none placeholder:text-black/35 focus:border-black/50";
const primary = "flex h-11 items-center justify-center gap-2 rounded-lg bg-[#1c1b19] px-5 text-[14px] font-medium text-white hover:bg-black disabled:opacity-60";
const secondary = "flex h-11 items-center justify-center rounded-lg border border-black/12 bg-white px-5 text-[14px] font-medium hover:border-black/30";

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [workspace, setWorkspace] = useState<{ id: number; name: string } | null>(null);
  const [name, setName] = useState("");
  const [project, setProject] = useState("");
  const [description, setDescription] = useState("");
  const [stack, setStack] = useState<string[]>([]);
  const [key, setKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<"agent" | "otel" | "prom">("agent");
  const [invites, setInvites] = useState([{ email: "", role: "member" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const fresh = new URLSearchParams(window.location.search).has("new");
    call("/v1/auth/me").then((me) => {
      if (me.workspace && me.project && !fresh) window.location.assign("/overview");
      else if (me.workspace && !fresh) { setWorkspace(me.workspace); setStep(1); }
      else setName(me.name ? `${me.name.split(" ")[0]}'s team` : "");
    }).catch(() => {});
  }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const api = typeof window === "undefined" ? "" : window.location.origin.replace("://wise.", "://wise-api.");
  const snippets = {
    agent: `# pm2, systemd, Docker, Kubernetes, log files\ncurl -fsSL ${api}/agent/install.sh | sh\ntracewise login --url ${api} --key ${key}\ntracewise detect && tracewise init && tracewise run`,
    otel: `OTEL_EXPORTER_OTLP_ENDPOINT=${api}/otlp\nOTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf\nOTEL_EXPORTER_OTLP_HEADERS=x-ingest-key=${key}`,
    prom: `Sources → Connect a source → Prometheus\nURL: http://your-prometheus:9090   (no key needed: Tracewise reads from it)`,
  };

  return (
    <AuthShell wide>
      <ol className="mb-10 flex items-center gap-2">
        {STEPS.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            <span className={cn("flex size-6 items-center justify-center rounded-full border border-black/15 text-[11.5px] text-black/50",
              i < step && "border-black bg-black text-white", i === step && "border-black text-black")}>
              {i < step ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("text-[13px]", i === step ? "text-black" : "text-black/45")}>{s}</span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-black/12" />}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => {
          const ws = await call("/v1/workspaces", "POST", { name });
          localStorage.setItem("tw_workspace", String(ws.id)); localStorage.removeItem("tw_project");
          setWorkspace(ws); setStep(1);
        }); }} className="flex flex-col gap-5">
          <div>
            <h1 className="display text-[44px] text-black">Name your workspace</h1>
            <p className="mt-3 text-[15px] text-black/60">One per company or team that shares on-call. You&apos;ll invite people to it.</p>
          </div>
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Workspace name</span>
            <input className={field} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Platform" required autoFocus />
            {name && <span className="font-mono text-[12px] text-black/45">{slugify(name) || "workspace"}</span>}</label>
          <button type="submit" className={primary} disabled={busy || name.trim().length < 2}>{busy && <Loader2 className="size-4 animate-spin" />}Create workspace</button>
        </form>
      )}

      {step === 1 && (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => {
          const p = await call(`/v1/workspaces/${workspace!.id}/projects`, "POST", { name: project, description, stack });
          localStorage.setItem("tw_project", String(p.id));
          const k = await call(`/v1/projects/${p.id}/keys`, "POST", { name: "Default" });
          setKey(k.key); setStep(2);
        }); }} className="flex flex-col gap-5">
          <div>
            <h1 className="display text-[44px] text-black">Add your first project</h1>
            <p className="mt-3 text-[15px] text-black/60">One system the agent looks after, like your API or checkout. Each project has its own services, incidents and keys.</p>
          </div>
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Project name</span>
            <input className={field} value={project} onChange={(e) => setProject(e.target.value)} placeholder="checkout-api" required autoFocus /></label>
          <div className="flex flex-col gap-2"><span className="text-[13px] font-medium">What does it run on?</span>
            <div className="flex flex-wrap gap-2">
              {STACKS.map((s) => {
                const on = stack.includes(s);
                return <button type="button" key={s} onClick={() => setStack(on ? stack.filter((x) => x !== s) : [...stack, s])}
                  className={cn("h-8 rounded-full border px-3.5 text-[13px] transition-colors", on ? "border-black bg-black text-white" : "border-black/15 bg-white hover:border-black/35")}>{s}</button>;
              })}
            </div>
            <span className="text-[12.5px] text-black/45">Helps the agent know where to look. Optional.</span>
          </div>
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Description</span>
            <textarea className="min-h-20 rounded-lg border border-black/12 bg-white px-3.5 py-2.5 text-[14px] outline-none placeholder:text-black/35 focus:border-black/50"
              value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Order intake API and its Postgres database" />
            <span className="text-[12.5px] text-black/45">The agent reads this when it investigates.</span></label>
          <button type="submit" className={primary} disabled={busy || project.trim().length < 2}>{busy && <Loader2 className="size-4 animate-spin" />}Create project</button>
        </form>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-5">
          <div>
            <h1 className="display text-[44px] text-black">Connect your telemetry</h1>
            <p className="mt-3 text-[15px] text-black/60">This is {project}&apos;s ingest key. Copy it now: for your security it&apos;s shown only once.</p>
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-black/12 bg-white px-3.5 py-3">
            <code className="min-w-0 flex-1 font-mono text-[12.5px] break-all">{key}</code>
            <button type="button" onClick={() => { navigator.clipboard?.writeText(key); setCopied(true); }}
              className="flex items-center gap-1.5 rounded-md border border-black/12 px-2.5 py-1 text-[12.5px]">{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}{copied ? "Copied" : "Copy"}</button>
          </div>
          <div>
            <div className="flex gap-1 border-b border-black/10">
              {([["agent", "Servers"], ["otel", "OpenTelemetry"], ["prom", "Prometheus & more"]] as const).map(([id, label]) => (
                <button key={id} onClick={() => setTab(id)} className={cn("-mb-px border-b-2 px-3 py-2 text-[13px]", tab === id ? "border-black text-black" : "border-transparent text-black/50")}>{label}</button>
              ))}
            </div>
            <pre className="mt-3 overflow-x-auto rounded-lg bg-[#0b0b0c] p-4 font-mono text-[12px] leading-relaxed text-white/90">{snippets[tab]}</pre>
          </div>
          <div className="flex gap-3">
            <button className={primary} onClick={() => setStep(3)}>Continue</button>
            <button className={secondary} onClick={() => setStep(3)}>I&apos;ll do this later</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => {
          const rows = invites.filter((i) => i.email.trim());
          for (const role of ["admin", "member", "viewer"]) {
            const emails = rows.filter((i) => i.role === role).map((i) => i.email.trim());
            if (emails.length) await call(`/v1/workspaces/${workspace!.id}/invites`, "POST", { emails, role });
          }
          window.location.assign("/overview");
        }); }} className="flex flex-col gap-5">
          <div>
            <h1 className="display text-[44px] text-black">Invite your team</h1>
            <p className="mt-3 text-[15px] text-black/60">They get an email with a link to join {workspace?.name}. It only works for that address and expires in 7 days.</p>
          </div>
          <div className="flex flex-col gap-2">
            {invites.map((inv, i) => (
              <div key={i} className="flex gap-2">
                <input className={field} type="email" value={inv.email} placeholder="teammate@company.com"
                  onChange={(e) => setInvites(invites.map((x, j) => j === i ? { ...x, email: e.target.value } : x))} />
                <select className="h-11 rounded-lg border border-black/12 bg-white px-3 text-[14px]" value={inv.role}
                  onChange={(e) => setInvites(invites.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}>
                  {ROLES.map(([r]) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}
                </select>
                {invites.length > 1 && <button type="button" onClick={() => setInvites(invites.filter((_, j) => j !== i))}
                  className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-black/12 bg-white" aria-label="Remove"><X className="size-4" /></button>}
              </div>
            ))}
            <button type="button" onClick={() => setInvites([...invites, { email: "", role: "member" }])}
              className="flex items-center gap-1.5 self-start text-[13px] text-black/60 hover:text-black"><Plus className="size-3.5" />Add another</button>
            <ul className="mt-1 text-[12.5px] text-black/45">{ROLES.map(([r, d]) => <li key={r}>{d}</li>)}</ul>
          </div>
          <div className="flex gap-3">
            <button type="submit" className={primary} disabled={busy}>{busy && <Loader2 className="size-4 animate-spin" />}{invites.some((i) => i.email.trim()) ? "Send invites" : "Finish"}</button>
            <button type="button" className={secondary} onClick={() => window.location.assign("/overview")}>Skip for now</button>
          </div>
        </form>
      )}
      {error && <p className="mt-5 rounded-lg bg-bad-soft px-3.5 py-2.5 text-[13px] text-bad">{error}</p>}
    </AuthShell>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STEPS = ["Workspace", "Project", "Team"];

async function call(path: string, method = "GET", body?: unknown) {
  const ws = localStorage.getItem("tw_workspace");
  const r = await fetch(`/api/tw${path}`, { method, body: body ? JSON.stringify(body) : undefined,
    headers: { "content-type": "application/json", ...(ws ? { "x-tracewise-workspace": ws } : {}) } });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) location.href = "/login?next=/onboarding";
  if (!r.ok) throw new Error(data.detail ?? "Something went wrong.");
  return data;
}

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [workspace, setWorkspace] = useState<{ id: number; name: string } | null>(null);
  const [name, setName] = useState("");
  const [project, setProject] = useState("Shopfront");
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    call("/v1/auth/me").then((me) => {
      if (me.workspace) location.href = "/incidents";
      else setName(me.name ? `${me.name.split(" ")[0]}'s team` : "");
    }).catch(() => {});
  }, []);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const createWorkspace = (e: React.FormEvent) => { e.preventDefault(); run(async () => {
    const ws = await call("/v1/workspaces", "POST", { name });
    localStorage.setItem("tw_workspace", String(ws.id));
    setWorkspace(ws); setStep(1);
  }); };
  const createProject = (e: React.FormEvent) => { e.preventDefault(); run(async () => {
    await call(`/v1/workspaces/${workspace!.id}/projects`, "POST", { name: project });
    setStep(2);
  }); };
  const invite = (e: React.FormEvent) => { e.preventDefault(); run(async () => {
    if (emails.trim()) await call(`/v1/workspaces/${workspace!.id}/invites`, "POST", { emails, role });
    location.href = "/incidents";
  }); };

  const input = "h-10 w-full rounded-lg border px-3 outline-none focus:border-foreground/40";
  return (
    <div className="w-full max-w-[460px]">
      <ol className="mb-5 flex items-center justify-center gap-2">
        {STEPS.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            <span className={cn("flex size-6 items-center justify-center rounded-full border text-[11.5px]",
              i < step && "border-foreground bg-foreground text-background", i === step && "border-foreground")}>
              {i < step ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("text-[12.5px]", i === step ? "text-foreground" : "text-muted-foreground")}>{s}</span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-8 bg-border" />}
          </li>
        ))}
      </ol>
      <div className="rounded-2xl border bg-background p-8 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        {step === 0 && (
          <form onSubmit={createWorkspace} className="flex flex-col gap-4">
            <div>
              <h1 className="text-[20px] font-medium tracking-tight">Create your workspace</h1>
              <p className="mt-1.5 text-muted-foreground">One per team that shares on-call. You can invite people next.</p>
            </div>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Workspace name</span>
              <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Payments SRE" required autoFocus /></label>
            <Button type="submit" size="lg" className="h-10" disabled={busy}>{busy && <Loader2 className="animate-spin" />}Create workspace</Button>
          </form>
        )}
        {step === 1 && (
          <form onSubmit={createProject} className="flex flex-col gap-4">
            <div>
              <h1 className="text-[20px] font-medium tracking-tight">Add your first project</h1>
              <p className="mt-1.5 text-muted-foreground">A system the agent looks after: an app, a set of services, an environment.</p>
            </div>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Project name</span>
              <input className={input} value={project} onChange={(e) => setProject(e.target.value)} required autoFocus /></label>
            <Button type="submit" size="lg" className="h-10" disabled={busy}>{busy && <Loader2 className="animate-spin" />}Continue</Button>
          </form>
        )}
        {step === 2 && (
          <form onSubmit={invite} className="flex flex-col gap-4">
            <div>
              <h1 className="text-[20px] font-medium tracking-tight">Invite your team</h1>
              <p className="mt-1.5 text-muted-foreground">They get an email with a link to join {workspace?.name}.</p>
            </div>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Emails, comma separated</span>
              <textarea className="min-h-20 rounded-lg border px-3 py-2 outline-none focus:border-foreground/40" value={emails}
                onChange={(e) => setEmails(e.target.value)} placeholder="priya@company.com, rahul@company.com" autoFocus /></label>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Role</span>
              <select className={input} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="admin">Admin: manage people, sources and agents</option>
                <option value="member">Member: follow and act on incidents</option>
                <option value="viewer">Viewer: read-only</option>
              </select></label>
            <div className="flex gap-2">
              <Button type="button" variant="outline" size="lg" className="h-10 flex-1" onClick={() => (location.href = "/incidents")}>Skip for now</Button>
              <Button type="submit" size="lg" className="h-10 flex-1" disabled={busy}>{busy && <Loader2 className="animate-spin" />}{emails.trim() ? "Send invites" : "Finish"}</Button>
            </div>
          </form>
        )}
        {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-[12.5px] text-bad">{error}</p>}
      </div>
    </div>
  );
}

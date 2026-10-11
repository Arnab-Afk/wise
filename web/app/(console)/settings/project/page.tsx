"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, switchTo } from "@/lib/api";
import { ago } from "@/lib/format";
import { canAdmin, refreshMe, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { KeyReveal } from "@/components/tw/key-reveal";

interface Project { id: number; name: string; slug: string; description: string | null; can_deploy: boolean; has_repo: boolean;
  services: number; incidents: number; sources: number }
interface Key { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; created_by: string | null }
const input = "h-9 rounded-lg border px-3 outline-none focus:border-foreground/40";

export default function ProjectSettings() {
  const me = useMe();
  const admin = canAdmin(me);
  const pid = me?.project?.id;
  const [project, setProject] = useState<Project | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [now, setNow] = useState(0);
  const [draft, setDraft] = useState<{ name?: string; description?: string }>({});
  const [keyName, setKeyName] = useState("");
  const [secret, setSecret] = useState<{ name: string; key: string } | null>(null);
  const [newProject, setNewProject] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    if (!pid) return;
    api<Project>(`/v1/projects/${pid}`).then((p) => { setProject(p); setNow(Date.now()); }).catch(() => {});
    if (admin) api<Key[]>(`/v1/projects/${pid}/keys`).then(setKeys).catch(() => {});
  }, [pid, admin]);
  useEffect(() => { load(); }, [load]);

  const run = async (k: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(k);
    try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(""); }
  };

  if (!me) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const name = draft.name ?? project?.name ?? "";
  const description = draft.description ?? project?.description ?? "";
  return (
    <>
      {project && (
        <Section title={`Project: ${project.name}`} description={`${project.services} services · ${project.incidents} incidents · ${project.sources} sources`}>
          <form className="flex flex-col gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault();
            run("save", () => api(`/v1/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ name, description }) })
              .then(() => { setDraft({}); return refreshMe(); }), "Project saved"); }}>
            <div className="flex gap-3">
              <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Name</span>
                <input className={input} value={name} disabled={!admin} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
              <label className="flex w-48 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Slug</span>
                <input className={`${input} font-mono text-[12.5px] text-muted-foreground`} value={project.slug} disabled /></label>
            </div>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Description (the agent reads this)</span>
              <input className={input} value={description} disabled={!admin} placeholder="e.g. Payments API on Kubernetes, Postgres, Stripe"
                onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
            {admin && <div><Button type="submit" variant="outline" disabled={busy === "save" || (draft.name === undefined && draft.description === undefined)}>Save</Button></div>}
          </form>
          <div className="flex flex-wrap gap-2 border-t px-5 py-3 text-[12.5px]">
            <span className="text-muted-foreground">What the agent can do here:</span>
            <Pill tone="ok" dot>investigate telemetry</Pill>
            <Pill tone={project.can_deploy ? "ok" : "neutral"} dot>{project.can_deploy ? "roll back, restart, flags" : "no deploy integration: hands over instead"}</Pill>
            <Pill tone={project.has_repo ? "ok" : "neutral"} dot>{project.has_repo ? "read code, write fixes" : "no repository connected"}</Pill>
          </div>
        </Section>
      )}

      {admin && project && (
        <Section title="Ingest keys" description="Anything sent with a key lands in this project only: agents, shippers, OpenTelemetry, webhooks.">
          <form className="flex items-end gap-3 border-b px-5 py-4" onSubmit={(e) => { e.preventDefault();
            run("key", () => api<{ name: string; key: string }>(`/v1/projects/${project.id}/keys`, { method: "POST", body: JSON.stringify({ name: keyName || "Ingest key" }) })
              .then((k) => { setSecret(k); setKeyName(""); })); }}>
            <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">New key</span>
              <input className={input} value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="e.g. production hosts, CI deploys, OTel collector" /></label>
            <Button type="submit" className="h-9" disabled={busy === "key"}>{busy === "key" ? <Loader2 className="animate-spin" /> : <KeyRound />}Create key</Button>
          </form>
          <div className="divide-y">
            {keys.length === 0 && <p className="px-5 py-6 text-muted-foreground">No keys yet. Create one to start sending telemetry.</p>}
            {keys.map((k) => (
              <div key={k.id} className="flex items-center gap-3 px-5 py-3">
                <KeyRound className="size-4 text-muted-foreground" />
                <span className="font-medium">{k.name}</span>
                <Tag mono>{k.prefix}…</Tag>
                <span className="ml-auto text-[12px] text-muted-foreground">
                  {k.last_used_at ? `last used ${ago(k.last_used_at, now)}` : "never used"} · created {ago(k.created_at, now)}{k.created_by ? ` by ${k.created_by}` : ""}
                </span>
                <Button variant="ghost" size="sm" onClick={() => confirm_(`Revoke "${k.name}"? Anything using it stops sending immediately.`) &&
                  run(`rv${k.id}`, () => api(`/v1/projects/${project.id}/keys/${k.id}`, { method: "DELETE" }), "Key revoked")}>Revoke</Button>
              </div>
            ))}
          </div>
        </Section>
      )}

      {admin && me.workspace && (
        <div id="new">
          <Section title="New project" description="A separate system with its own services, telemetry, incidents and keys.">
            <form className="flex items-end gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault();
              run("new", async () => {
                const p = await api<{ id: number }>(`/v1/workspaces/${me.workspace!.id}/projects`, { method: "POST", body: JSON.stringify({ name: newProject }) });
                const k = await api<{ name: string; key: string }>(`/v1/projects/${p.id}/keys`, { method: "POST", body: JSON.stringify({ name: "Default" }) });
                try { localStorage.setItem("tw_project", String(p.id)); } catch {}
                setNewProject(""); setSecret(k); await refreshMe();
              }, "Project created"); }}>
              <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Name</span>
                <input className={input} value={newProject} onChange={(e) => setNewProject(e.target.value)} placeholder="Checkout platform" required /></label>
              <Button type="submit" variant="outline" className="h-9" disabled={busy === "new"}><Plus />Create project</Button>
            </form>
          </Section>
        </div>
      )}

      {me.role === "owner" && project && (
        <Section title="Delete project" description="Deletes every service, metric, log, incident, source and key in it. This can't be undone.">
          <form className="flex items-end gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault();
            run("del", () => api(`/v1/projects/${project.id}`, { method: "DELETE", body: JSON.stringify({ confirm }) })
              .then(() => switchTo(me.workspace?.id ?? null, null)), "Project deleted"); }}>
            <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Type <span className="font-mono">{project.name}</span> to confirm</span>
              <input className={input} value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
            <Button type="submit" variant="destructive" className="h-9" disabled={confirm !== project.name || busy === "del"}>Delete project</Button>
          </form>
        </Section>
      )}
      <KeyReveal secret={secret} onClose={() => { setSecret(null); load(); }} />
    </>
  );
}

function confirm_(msg: string) {
  return window.confirm(msg);
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { FolderKanban, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { canAdmin, refreshMe, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";

interface Member { id: number; email: string; name: string | null; avatar_url: string | null; role: string; last_login_at: string | null; joined_at: string }
interface Invite { id: number; email: string; role: string; created_at: string; expires_at: string; invited_by_name: string | null; invited_by_email: string | null }
interface Project { id: number; name: string; slug: string; description: string | null; created_at: string; created_by_name: string | null }

const ROLE_TONE = { owner: "dark", admin: "info", member: "neutral", viewer: "neutral" } as const;
const input = "h-9 rounded-lg border px-3 outline-none focus:border-foreground/40";

export default function WorkspaceSettings() {
  const me = useMe();
  const ws = me?.workspace;
  const admin = canAdmin(me);
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [now, setNow] = useState(0);
  const [draft, setName] = useState<string | null>(null); // null until edited
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState("member");
  const [project, setProject] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    if (!ws) return;
    api<{ members: Member[]; invites: Invite[] }>(`/v1/workspaces/${ws.id}/members`).then((d) => {
      setMembers(d.members); setInvites(d.invites); setNow(Date.now());
    }).catch(() => {});
    api<Project[]>(`/v1/workspaces/${ws.id}/projects`).then(setProjects).catch(() => {});
  }, [ws]);
  useEffect(() => { load(); }, [load]);

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(""); }
  };

  if (!ws) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const name = draft ?? ws.name;
  return (
    <>
      <Section title="Workspace" description="Everyone in this workspace sees the same incidents, sources and coding agents.">
        <form className="flex items-end gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault();
          run("rename", () => api(`/v1/workspaces/${ws.id}`, { method: "PATCH", body: JSON.stringify({ name }) }).then(refreshMe), "Workspace renamed"); }}>
          <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Name</span>
            <input className={input} value={name} onChange={(e) => setName(e.target.value)} disabled={!admin} /></label>
          <label className="flex w-48 flex-col gap-1.5"><span className="text-[12.5px] font-medium">URL slug</span>
            <input className={`${input} font-mono text-[12.5px] text-muted-foreground`} value={ws.slug} disabled /></label>
          {admin && <Button type="submit" variant="outline" className="h-9" disabled={busy === "rename" || name === ws.name}>Save</Button>}
        </form>
      </Section>

      <Section title="Members" description={`${members.length} ${members.length === 1 ? "person" : "people"} · your role: ${ws.role}`}>
        {admin && (
          <form className="flex flex-wrap items-end gap-3 border-b px-5 py-4" onSubmit={(e) => { e.preventDefault();
            run("invite", async () => {
              const r = await api<{ sent: unknown[]; skipped: { email: string; reason: string }[] }>(`/v1/workspaces/${ws.id}/invites`,
                { method: "POST", body: JSON.stringify({ emails, role }) });
              toast.success(`${r.sent.length} invitation${r.sent.length === 1 ? "" : "s"} sent`);
              r.skipped.forEach((s) => toast(`${s.email}: ${s.reason}`));
              setEmails("");
            }); }}>
            <label className="flex min-w-60 flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Invite by email</span>
              <input className={input} value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="priya@company.com, rahul@company.com" required /></label>
            <label className="flex flex-col gap-1.5"><span className="text-[12.5px] font-medium">Role</span>
              <select className={input} value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="admin">Admin</option><option value="member">Member</option><option value="viewer">Viewer</option>
              </select></label>
            <Button type="submit" className="h-9" disabled={busy === "invite"}>{busy === "invite" ? <Loader2 className="animate-spin" /> : <Plus />}Send invites</Button>
          </form>
        )}
        <div className="divide-y">
          {members.map((m) => (
            <div key={m.id} className="flex items-center gap-3 px-5 py-3">
              <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-[12px] font-medium">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {m.avatar_url ? <img src={m.avatar_url} alt="" className="size-8" /> : (m.name || m.email).slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{m.name || m.email}{m.id === me?.id && <span className="ml-1.5 text-[12px] font-normal text-muted-foreground">(you)</span>}</p>
                <p className="truncate text-[12.5px] text-muted-foreground">{m.email} · last active {ago(m.last_login_at, now)}</p>
              </div>
              {admin && m.id !== me?.id && (me?.role === "owner" || m.role !== "owner") ? (
                <select className="h-8 rounded-lg border px-2 text-[12.5px]" value={m.role}
                  onChange={(e) => run(`role${m.id}`, () => api(`/v1/workspaces/${ws.id}/members/${m.id}`,
                    { method: "PATCH", body: JSON.stringify({ role: e.target.value }) }), "Role updated")}>
                  {(me?.role === "owner" ? ["owner", "admin", "member", "viewer"] : ["admin", "member", "viewer"]).map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              ) : <Pill tone={ROLE_TONE[m.role as keyof typeof ROLE_TONE] ?? "neutral"}>{m.role}</Pill>}
              {(admin || m.id === me?.id) && (
                <Button variant="ghost" size="sm" onClick={() => confirm(m.id === me?.id ? `Leave ${ws.name}?` : `Remove ${m.email} from ${ws.name}?`)
                  && run(`rm${m.id}`, () => api(`/v1/workspaces/${ws.id}/members/${m.id}`, { method: "DELETE" })
                    .then(() => m.id === me?.id && (location.href = "/onboarding")), "Removed")}>
                  {m.id === me?.id ? "Leave" : "Remove"}
                </Button>
              )}
            </div>
          ))}
        </div>
        {invites.length > 0 && (
          <div className="border-t">
            <p className="micro px-5 pt-3 pb-1">pending invitations</p>
            {invites.map((i) => (
              <div key={i.id} className="flex items-center gap-3 px-5 py-2.5">
                <span className="min-w-0 flex-1 truncate">{i.email}</span>
                <Tag>{i.role}</Tag>
                <span className="text-[12px] text-muted-foreground">sent {ago(i.created_at, now)} by {i.invited_by_name ?? i.invited_by_email}</span>
                <Button variant="ghost" size="sm" onClick={() => run(`re${i.id}`, () => api(`/v1/invites/${i.id}/resend`, { method: "POST" }), "Invitation re-sent")}>Resend</Button>
                <Button variant="ghost" size="sm" onClick={() => run(`rv${i.id}`, () => api(`/v1/invites/${i.id}`, { method: "DELETE" }), "Invitation revoked")}>Revoke</Button>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Projects" description="Systems the agent looks after in this workspace.">
        {admin && (
          <form className="flex items-end gap-3 border-b px-5 py-4" onSubmit={(e) => { e.preventDefault();
            run("project", () => api(`/v1/workspaces/${ws.id}/projects`, { method: "POST", body: JSON.stringify({ name: project }) })
              .then(() => setProject("")), "Project created"); }}>
            <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">New project</span>
              <input className={input} value={project} onChange={(e) => setProject(e.target.value)} placeholder="Checkout platform" required /></label>
            <Button type="submit" variant="outline" className="h-9" disabled={busy === "project"}><Plus />Add project</Button>
          </form>
        )}
        <div className="divide-y">
          {projects.length === 0 && <p className="px-5 py-6 text-muted-foreground">No projects yet.</p>}
          {projects.map((p) => (
            <div key={p.id} className="flex items-center gap-3 px-5 py-3">
              <FolderKanban className="size-4 text-muted-foreground" />
              <span className="font-medium">{p.name}</span>
              <Tag mono>{p.slug}</Tag>
              <span className="ml-auto text-[12px] text-muted-foreground">created {ago(p.created_at, now)}{p.created_by_name ? ` by ${p.created_by_name}` : ""}</span>
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}

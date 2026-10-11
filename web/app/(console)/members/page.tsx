"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { canAdmin, useMe } from "@/hooks/use-me";
import { Avatar } from "@/components/tw/avatar";
import { PageBody, PageTitle } from "@/components/tw/page-title";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";

interface Member { id: number; email: string; name: string | null; avatar_url: string | null; role: string; last_login_at: string | null }
interface Invite { id: number; email: string; role: string; created_at: string; expires_at: string; invited_by_name: string | null; invited_by_email: string | null }
const CAN: Record<string, string> = {
  admin: "Admin: invite people, manage projects, teams, sources and coding agents.",
  member: "Member: follow incidents live and act on them.",
  viewer: "Viewer: see incidents and timelines, read-only.",
};

export default function MembersPage() {
  const me = useMe();
  const ws = me?.workspace;
  const admin = canAdmin(me);
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState("");
  const [now, setNow] = useState(0);
  const load = useCallback(() => {
    if (ws) api<{ members: Member[]; invites: Invite[] }>(`/v1/workspaces/${ws.id}/members`)
      .then((d) => { setMembers(d.members); setInvites(d.invites); setNow(Date.now()); }).catch(() => {});
  }, [ws]);
  useEffect(() => { load(); }, [load]);
  const run = async (k: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(k);
    try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(""); }
  };

  return (
    <PageBody>
      <PageTitle title="Members" description={ws ? `People with access to ${ws.name}.` : " "} />
      {admin && ws && (
        <section className="rounded-xl border p-6">
          <h2 className="text-[16px] font-medium">Invite people</h2>
          <p className="mt-1 text-[13.5px] text-muted-foreground">They get an email with a link. It works only when they sign in with that address, and expires in 7 days.</p>
          <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault();
            run("invite", async () => {
              const r = await api<{ sent: unknown[]; skipped: { email: string; reason: string }[] }>(`/v1/workspaces/${ws.id}/invites`,
                { method: "POST", body: JSON.stringify({ emails: email, role }) });
              if (r.sent.length) toast.success(`Invitation sent to ${email}`);
              r.skipped.forEach((s) => toast(`${s.email}: ${s.reason}`));
              setEmail("");
            }); }}>
            <input className="h-10 min-w-0 flex-1 rounded-lg border px-3 outline-none focus:border-foreground/40" type="text" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com (or several, comma separated)" required />
            <select className="h-10 w-36 rounded-lg border px-3" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="admin">Admin</option><option value="member">Member</option><option value="viewer">Viewer</option>
            </select>
            <Button type="submit" className="h-10" disabled={busy === "invite"}>{busy === "invite" && <Loader2 className="animate-spin" />}Send invite</Button>
          </form>
          <p className="mt-2 text-[12.5px] text-muted-foreground">{CAN[role]}</p>
        </section>
      )}
      <section>
        <h2 className="mb-3 text-[16px] font-medium">Members <span className="text-muted-foreground">{members.length}</span></h2>
        <div className="divide-y rounded-xl border">
          {members.map((m) => (
            <div key={m.id} className="flex items-center gap-4 px-5 py-4">
              <Avatar name={m.name || m.email} src={m.avatar_url} size={38} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{m.name || m.email.split("@")[0]}{m.id === me?.id && <span className="ml-2 text-[12.5px] font-normal text-muted-foreground">You</span>}</p>
                <p className="truncate text-[13px] text-muted-foreground">{m.email}{m.last_login_at ? ` · active ${ago(m.last_login_at, now)}` : ""}</p>
              </div>
              {admin && m.id !== me?.id && (me?.role === "owner" || m.role !== "owner") ? (
                <>
                  <select className="h-9 w-36 rounded-lg border px-3 text-[13px] capitalize" value={m.role}
                    onChange={(e) => run(`r${m.id}`, () => api(`/v1/workspaces/${ws!.id}/members/${m.id}`, { method: "PATCH", body: JSON.stringify({ role: e.target.value }) }), "Role updated")}>
                    {(me?.role === "owner" ? ["owner", "admin", "member", "viewer"] : ["admin", "member", "viewer"]).map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}
                  </select>
                  <Button variant="ghost" onClick={() => confirm(`Remove ${m.email} from ${ws!.name}?`) &&
                    run(`x${m.id}`, () => api(`/v1/workspaces/${ws!.id}/members/${m.id}`, { method: "DELETE" }), "Removed")}>Remove</Button>
                </>
              ) : (
                <Pill tone={m.role === "owner" ? "ok" : "neutral"} className="capitalize">{m.role}</Pill>
              )}
              {m.id === me?.id && me?.role !== "owner" && (
                <Button variant="ghost" onClick={() => confirm(`Leave ${ws!.name}?`) &&
                  run("leave", () => api(`/v1/workspaces/${ws!.id}/members/${m.id}`, { method: "DELETE" }).then(() => window.location.assign("/onboarding")))}>Leave</Button>
              )}
            </div>
          ))}
        </div>
      </section>
      {admin && invites.length > 0 && (
        <section>
          <h2 className="mb-3 text-[16px] font-medium">Pending invitations</h2>
          <div className="divide-y rounded-xl border">
            {invites.map((i) => (
              <div key={i.id} className="flex items-center gap-4 px-5 py-4">
                <Avatar name={i.email} size={38} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{i.email}</p>
                  <p className="text-[13px] text-muted-foreground">Invited by {i.invited_by_name ?? i.invited_by_email} {ago(i.created_at, now)}, expires {new Date(i.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</p>
                </div>
                <Tag className="capitalize">{i.role}</Tag>
                <Button variant="ghost" onClick={() => run(`re${i.id}`, () => api(`/v1/invites/${i.id}/resend`, { method: "POST" }), "Invitation re-sent")}>Resend</Button>
                <Button variant="ghost" onClick={() => run(`rv${i.id}`, () => api(`/v1/invites/${i.id}`, { method: "DELETE" }), "Invitation revoked")}>Revoke</Button>
              </div>
            ))}
          </div>
        </section>
      )}
    </PageBody>
  );
}

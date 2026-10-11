"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { canAdmin, useMe } from "@/hooks/use-me";
import { Avatar } from "@/components/tw/avatar";
import { PageBody, PageTitle } from "@/components/tw/page-title";
import { Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface Person { id: number; email: string; name: string | null; avatar_url: string | null }
interface Team { id: number; name: string; description: string | null; members: Person[]; projects: { id: number; name: string; slug: string }[] }

export default function TeamsPage() {
  const me = useMe();
  const ws = me?.workspace;
  const admin = canAdmin(me);
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [editing, setEditing] = useState<Team | "new" | null>(null);
  const load = useCallback(() => {
    if (!ws) return;
    api<Team[]>(`/v1/workspaces/${ws.id}/teams`).then(setTeams).catch(() => {});
    api<{ members: Person[] }>(`/v1/workspaces/${ws.id}/members`).then((d) => setPeople(d.members)).catch(() => {});
  }, [ws]);
  useEffect(() => { load(); }, [load]);

  return (
    <PageBody>
      <PageTitle title="Teams" description="Group members by what they look after. A team on call for a project gets its incident emails.">
        {admin && <Button onClick={() => setEditing("new")}>New team</Button>}
      </PageTitle>
      {teams?.length === 0 && (
        <div className="rounded-xl border px-6 py-14 text-center">
          <p className="font-medium">No teams yet</p>
          <p className="mx-auto mt-1 max-w-md text-[13.5px] text-muted-foreground">Without teams, everyone in the workspace gets every project&apos;s incident emails. Create a team and put it on call for the projects it owns.</p>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {teams?.map((t) => (
          <button key={t.id} onClick={() => admin && setEditing(t)} className={cn("rounded-xl border p-6 text-left", admin && "transition-colors hover:border-foreground/25")}>
            <p className="text-[16px] font-medium">{t.name}</p>
            <p className="mt-1 min-h-[20px] text-[13.5px] text-muted-foreground">{t.description}</p>
            <div className="mt-4 flex flex-wrap gap-1.5">{t.projects.map((p) => <Tag key={p.id} mono>on call: {p.slug}</Tag>)}</div>
            <div className="mt-5 flex items-center gap-2">
              <span className="flex -space-x-2">{t.members.slice(0, 5).map((m) => <Avatar key={m.id} name={m.name || m.email} src={m.avatar_url} size={30} className="ring-2 ring-background" />)}</span>
              <span className="text-[13.5px] text-muted-foreground">{t.members.length} {t.members.length === 1 ? "member" : "members"}</span>
            </div>
          </button>
        ))}
      </div>
      {editing && ws && <TeamDialog team={editing === "new" ? null : editing} people={people} projects={me?.projects ?? []}
        workspaceId={ws.id} onClose={() => { setEditing(null); load(); }} />}
    </PageBody>
  );
}

function TeamDialog({ team, people, projects, workspaceId, onClose }: {
  team: Team | null; people: Person[]; projects: { id: number; name: string; slug: string }[]; workspaceId: number; onClose: () => void;
}) {
  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [members, setMembers] = useState<number[]>(team?.members.map((m) => m.id) ?? []);
  const [owned, setOwned] = useState<number[]>(team?.projects.map((p) => p.id) ?? []);
  const [busy, setBusy] = useState(false);
  const toggle = (list: number[], set: (v: number[]) => void, id: number) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (!team) {
        await api(`/v1/workspaces/${workspaceId}/teams`, { method: "POST", body: JSON.stringify({ name, description, member_ids: members, project_ids: owned }) });
      } else {
        await api(`/v1/teams/${team.id}`, { method: "PATCH", body: JSON.stringify({ name, description, project_ids: owned }) });
        const before = team.members.map((m) => m.id);
        for (const id of members.filter((m) => !before.includes(m))) await api(`/v1/teams/${team.id}/members`, { method: "POST", body: JSON.stringify({ user_id: id }) });
        for (const id of before.filter((m) => !members.includes(m))) await api(`/v1/teams/${team.id}/members/${id}`, { method: "DELETE" });
      }
      toast.success(team ? "Team saved" : "Team created");
      onClose();
    } catch (err) { toast.error((err as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!team || !confirm(`Delete the ${team.name} team? Its members stay in the workspace.`)) return;
    await api(`/v1/teams/${team.id}`, { method: "DELETE" }).catch((e) => toast.error(e.message));
    onClose();
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle className="text-[17px]">{team ? team.name : "New team"}</DialogTitle>
          <DialogDescription>Teams group people by what they look after.</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Name</span>
            <input className="h-10 rounded-lg border px-3 outline-none focus:border-foreground/40" value={name} onChange={(e) => setName(e.target.value)} placeholder="Platform" required autoFocus /></label>
          <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Description</span>
            <input className="h-10 rounded-lg border px-3 outline-none focus:border-foreground/40" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Owns the shared cloud infrastructure." /></label>
          <div className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Members</span>
            <div className="max-h-48 divide-y overflow-y-auto rounded-lg border">
              {people.map((p) => (
                <label key={p.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted/50">
                  <input type="checkbox" checked={members.includes(p.id)} onChange={() => toggle(members, setMembers, p.id)} />
                  <Avatar name={p.name || p.email} src={p.avatar_url} size={24} />
                  <span className="min-w-0 flex-1 truncate text-[13.5px]">{p.name || p.email}</span>
                  <span className="truncate text-[12px] text-muted-foreground">{p.email}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">On call for</span>
            <div className="flex flex-wrap gap-1.5">
              {projects.map((p) => {
                const on = owned.includes(p.id);
                return <button type="button" key={p.id} onClick={() => toggle(owned, setOwned, p.id)}
                  className={cn("flex h-7 items-center gap-1 rounded-full border px-3 font-mono text-[12px]", on ? "border-foreground bg-foreground text-background" : "hover:border-foreground/30")}>
                  {p.slug}{on && <X className="size-3" />}</button>;
              })}
            </div>
            <span className="text-[12px] text-muted-foreground">Members get these projects&apos; incident emails, by their own notification setting.</span>
          </div>
          <div className="-mx-4 -mb-4 flex items-center gap-2 border-t px-4 py-3">
            {team && <Button type="button" variant="ghost" className="text-bad" onClick={remove}>Delete team</Button>}
            <span className="flex-1" />
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || name.trim().length < 2}>{busy && <Loader2 className="animate-spin" />}{team ? "Save" : "Create team"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

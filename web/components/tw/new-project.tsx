"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { refreshMe, useMe } from "@/hooks/use-me";
import { KeyReveal } from "@/components/tw/key-reveal";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const STACKS = ["Kubernetes", "Docker", "pm2", "systemd", "VMs", "Serverless", "Postgres", "Redis", "Kafka", "Node.js", "Python", "Go", "Java"];
const input = "h-10 w-full rounded-lg border px-3 outline-none focus:border-foreground/40";

/** Create a project (iac-style modal), then show its first ingest key once and switch to it. */
export function NewProjectDialog({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; onCreated?: () => void;
}) {
  const me = useMe();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [stack, setStack] = useState<string[]>([]);
  const [teamId, setTeamId] = useState("");
  const [teams, setTeams] = useState<{ id: number; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<{ name: string; key: string } | null>(null);
  const [created, setCreated] = useState<number | null>(null);

  const wsId = me?.workspace?.id;
  useEffect(() => {
    if (open && wsId) api<{ id: number; name: string }[]>(`/v1/workspaces/${wsId}/teams`).then(setTeams).catch(() => {});
  }, [open, wsId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!me?.workspace) return;
    setBusy(true);
    try {
      const p = await api<{ id: number; name: string }>(`/v1/workspaces/${me.workspace.id}/projects`, {
        method: "POST", body: JSON.stringify({ name, description, stack, team_id: teamId ? Number(teamId) : undefined }) });
      const k = await api<{ name: string; key: string }>(`/v1/projects/${p.id}/keys`, { method: "POST", body: JSON.stringify({ name: "Default" }) });
      setCreated(p.id);
      onOpenChange(false);
      setSecret({ name: `${p.name}: Default`, key: k.key });
      setName(""); setDescription(""); setStack([]); setTeamId("");
      onCreated?.();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle className="text-[17px]">New project</DialogTitle>
            <DialogDescription>One system, like your API or data pipeline. It gets its own services, incidents and ingest keys.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Name</span>
              <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="orders-platform" required autoFocus /></label>
            <div className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Runs on</span>
              <div className="flex flex-wrap gap-1.5">
                {STACKS.map((s) => {
                  const on = stack.includes(s);
                  return <button type="button" key={s} onClick={() => setStack(on ? stack.filter((x) => x !== s) : [...stack, s])}
                    className={cn("h-7 rounded-full border px-3 text-[12.5px]", on ? "border-foreground bg-foreground text-background" : "hover:border-foreground/30")}>{s}</button>;
                })}
              </div>
            </div>
            {teams.length > 0 && (
              <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">On-call team</span>
                <select className={input} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                  <option value="">Everyone in the workspace</option>
                  {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
                <span className="text-[12px] text-muted-foreground">Gets this project&apos;s incident emails.</span></label>
            )}
            <label className="flex flex-col gap-1.5"><span className="text-[13px] font-medium">Description</span>
              <textarea className="min-h-20 rounded-lg border px-3 py-2 outline-none focus:border-foreground/40" value={description}
                onChange={(e) => setDescription(e.target.value)} />
              <span className="text-[12px] text-muted-foreground">Optional. The agent reads it when it investigates.</span></label>
            <div className="-mx-4 -mb-4 flex justify-end gap-2 border-t px-4 py-3">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={busy || name.trim().length < 2}>{busy && <Loader2 className="animate-spin" />}Create project</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <KeyReveal secret={secret} onClose={() => {
        setSecret(null);
        try { if (created) localStorage.setItem("tw_project", String(created)); } catch {}
        refreshMe().then(() => window.location.assign("/sources"));
      }} />
    </>
  );
}

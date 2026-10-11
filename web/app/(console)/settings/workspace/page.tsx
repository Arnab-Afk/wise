"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { canAdmin, refreshMe, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { Button } from "@/components/ui/button";

const input = "h-9 rounded-lg border px-3 outline-none focus:border-foreground/40";

export default function WorkspaceSettings() {
  const me = useMe();
  const ws = me?.workspace;
  const admin = canAdmin(me);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!ws) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const name = draft ?? ws.name;
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`/v1/workspaces/${ws.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
      await refreshMe();
      setDraft(null);
      toast.success("Workspace renamed");
    } catch (err) { toast.error((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <>
      <Section title="Workspace" description="Everyone in this workspace shares its projects, teams and coding agents.">
        <form className="flex items-end gap-3 px-5 py-4" onSubmit={save}>
          <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Name</span>
            <input className={input} value={name} onChange={(e) => setDraft(e.target.value)} disabled={!admin} /></label>
          <label className="flex w-48 flex-col gap-1.5"><span className="text-[12.5px] font-medium">URL slug</span>
            <input className={`${input} font-mono text-[12.5px] text-muted-foreground`} value={ws.slug} disabled /></label>
          {admin && <Button type="submit" variant="outline" className="h-9" disabled={busy || name === ws.name}>Save</Button>}
        </form>
      </Section>
      <p className="text-[13.5px] text-muted-foreground">
        Members and invitations are under <a href="/members" className="underline">People → Members</a>, teams under{" "}
        <a href="/teams" className="underline">People → Teams</a>, and projects on the <a href="/overview" className="underline">Overview</a>.
      </p>
    </>
  );
}

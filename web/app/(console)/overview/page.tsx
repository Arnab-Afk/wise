"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, switchTo } from "@/lib/api";
import { ago } from "@/lib/format";
import { canAdmin, useMe } from "@/hooks/use-me";
import { NewProjectDialog } from "@/components/tw/new-project";
import { PageBody, PageTitle } from "@/components/tw/page-title";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";

interface ProjectCard {
  id: number; name: string; slug: string; description: string | null; stack: string[]; services: number; sources: number;
  open_incidents: number; resolved_30d: number; last_incident_at: string | null; last_data_at: string | null;
  teams: string[]; can_deploy: boolean; has_repo: boolean;
}
interface Overview { workspace: { name: string }; projects: ProjectCard[]; members: number; teams: number; coding_agents: number; open_incidents: number }

export default function OverviewPage() {
  const me = useMe();
  const [data, setData] = useState<Overview | null>(null);
  const [creating, setCreating] = useState(false);
  const [now, setNow] = useState(0);
  const wsId = me?.workspace?.id;
  const load = useCallback(() => {
    if (wsId) api<Overview>(`/v1/workspaces/${wsId}/overview`).then((d) => { setData(d); setNow(Date.now()); }).catch(() => {});
  }, [wsId]);
  useEffect(() => { load(); }, [load]);

  const stats = data ? [
    ["Projects", data.projects.length], ["Open incidents", data.open_incidents], ["Members", data.members], ["Coding agents", data.coding_agents],
  ] as const : [];
  return (
    <PageBody>
      <PageTitle title="Overview" description={data ? `Everything shared in ${data.workspace.name}.` : " "} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-xl border px-5 py-4">
            <p className="text-[13px] text-muted-foreground">{label}</p>
            <p className={`num mt-2 text-[28px] font-medium ${label === "Open incidents" && value ? "text-bad" : ""}`}>{value}</p>
          </div>
        ))}
        {!data && Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-[94px] animate-pulse rounded-xl bg-muted" />)}
      </div>
      <div>
        <div className="mb-4 flex items-center">
          <h2 className="flex-1 text-[17px] font-medium">Projects</h2>
          {canAdmin(me) && <Button variant="outline" onClick={() => setCreating(true)}><Plus />New project</Button>}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {data?.projects.map((p) => (
            <button key={p.id} onClick={() => switchTo(me?.workspace?.id ?? null, p.id)}
              className="flex flex-col rounded-xl border p-5 text-left transition-colors hover:border-foreground/25">
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] font-semibold">
                  {(p.stack[0] ?? p.name).slice(0, 3).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-medium">{p.name}</p>
                  <p className="truncate font-mono text-[12px] text-muted-foreground">{p.stack.length ? p.stack.join(" / ") : p.slug}</p>
                </div>
                {p.open_incidents > 0 ? <Pill tone="bad" dot>{p.open_incidents} open</Pill> : <Pill tone="ok" dot>all clear</Pill>}
              </div>
              <p className="mt-4 line-clamp-2 min-h-[40px] text-[13.5px] text-muted-foreground">{p.description || "No description yet."}</p>
              <div className="mt-4 flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
                <Tag>{p.services} services</Tag><Tag>{p.sources} sources</Tag><Tag>{p.resolved_30d} fixed in 30d</Tag>
                {p.teams.map((t) => <Tag key={t}>on call: {t}</Tag>)}
                <span className="ml-auto">{p.last_data_at ? `data ${ago(p.last_data_at, now)}` : "no data yet"}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
      <NewProjectDialog open={creating} onOpenChange={setCreating} onCreated={load} />
    </PageBody>
  );
}

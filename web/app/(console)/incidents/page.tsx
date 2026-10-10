"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Siren, Search, ArrowUpRight } from "lucide-react";
import { api, ACTIVE, type Incident } from "@/lib/api";
import { ago, duration, usd } from "@/lib/format";
import { usePoll, useStream } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { Pill, SeverityBars, StatusPill, Tag } from "@/components/tw/pills";
import { cn } from "@/lib/utils";

type Tab = "active" | "resolved" | "escalated";

export default function IncidentsPage() {
  const [rows, setRows] = useState<Incident[] | null>(null);
  const [tab, setTab] = useState<Tab>("active");
  const [query, setQuery] = useState("");
  const [now, setNow] = useState(0); // set after mount: Cache Components prerenders this page
  const load = () => api<Incident[]>("/v1/incidents?limit=200").then((r) => { setRows(r); setNow(Date.now()); }).catch(() => {});
  usePoll(load, 5000);
  useStream((e) => { if (e.type === "incident_opened" || e.type === "step") load(); });

  const groups = useMemo(() => {
    const all = rows ?? [];
    return {
      active: all.filter((r) => ACTIVE.includes(r.status)),
      resolved: all.filter((r) => r.status === "resolved"),
      escalated: all.filter((r) => r.status === "escalated"),
    };
  }, [rows]);

  // Open the tab that has something in it on first load.
  const shown = groups[tab].filter((r) => !query ||
    `${r.title} ${r.services.join(" ")} ${r.root_cause ?? ""}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <PageHeader icon={Siren} title="Incidents">
        <label className="flex h-8 w-64 items-center gap-2 rounded-lg border px-2.5 text-muted-foreground focus-within:border-foreground/30">
          <Search className="size-3.5" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search incidents, services, causes"
            className="w-full bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground" />
        </label>
      </PageHeader>

      <div className="flex-1 overflow-y-auto px-5 py-5">
        <Stats rows={rows ?? []} />

        <div className="mt-5 rounded-xl border bg-sidebar/60 p-1.5">
          <div className="flex items-center gap-1 px-1 pt-0.5 pb-1.5">
            {(["active", "resolved", "escalated"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={cn("flex h-8 items-center gap-2 rounded-lg px-3 text-[13.5px] capitalize text-muted-foreground transition-colors hover:text-foreground",
                  tab === t && "border bg-background text-foreground shadow-[0_1px_1px_rgba(0,0,0,0.03)]")}>
                {t}
                <span className={cn("num rounded-md px-1.5 text-[11px]",
                  t === "active" ? "bg-info-soft text-info" : t === "resolved" ? "bg-ok-soft text-ok" : "bg-muted text-muted-foreground")}>
                  {groups[t].length}
                </span>
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-1.5">
            {rows === null && Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-[62px] animate-pulse rounded-lg border bg-background" />
            ))}
            {rows !== null && shown.length === 0 && (
              <div className="rounded-lg border bg-background">
                <Empty title={tab === "active" ? "Nothing is on fire" : `No ${tab} incidents`}>
                  {tab === "active" ? "The detector is watching every service against its own baseline. New incidents appear here the moment they open." : null}
                </Empty>
              </div>
            )}
            {shown.map((r) => <IncidentRow key={r.id} incident={r} now={now} />)}
          </div>
        </div>
      </div>
    </>
  );
}

function IncidentRow({ incident: r, now }: { incident: Incident; now: number }) {
  const took = r.resolved_at ? new Date(r.resolved_at).getTime() - new Date(r.opened_at).getTime() : now - new Date(r.opened_at).getTime();
  return (
    <Link href={`/incidents/${r.id}`}
      className="group flex items-center gap-3.5 rounded-lg border bg-background px-4 py-3 transition-colors hover:border-foreground/20">
      <SeverityBars severity={r.severity} />
      <span className="num w-9 shrink-0 text-[12px] text-muted-foreground">#{r.id}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{r.title}</p>
        {r.root_cause && <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">{r.root_cause}</p>}
      </div>
      <div className="hidden shrink-0 items-center gap-1.5 lg:flex">
        {r.services.slice(0, 3).map((s) => <Tag key={s} mono>{s}</Tag>)}
        {r.services.length > 3 && <Tag mono>+{r.services.length - 3}</Tag>}
        {r.scenario && <Pill tone="neutral">{r.scenario}</Pill>}
      </div>
      <StatusPill status={r.status} />
      <div className="num hidden w-28 shrink-0 text-right text-[12px] text-muted-foreground md:block">
        {duration(took)} · {usd(r.cost_usd)}
      </div>
      <span className="w-16 shrink-0 text-right text-[12px] text-muted-foreground">{ago(r.opened_at, now)}</span>
      <ArrowUpRight className="size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
    </Link>
  );
}

function Stats({ rows }: { rows: Incident[] }) {
  const done = rows.filter((r) => r.status === "resolved" && r.resolved_at);
  const mttr = done.length ? done.reduce((a, r) => a + (new Date(r.resolved_at!).getTime() - new Date(r.opened_at).getTime()), 0) / done.length : NaN;
  const closed = rows.filter((r) => r.status === "resolved" || r.status === "escalated");
  const auto = closed.length ? done.length / closed.length : NaN;
  const cost = done.length ? done.reduce((a, r) => a + Number(r.cost_usd ?? 0), 0) / done.length : NaN;
  const items = [
    { label: "Resolved by the agent", value: Number.isFinite(auto) ? `${Math.round(auto * 100)}%` : "—", sub: `${done.length} of ${closed.length} closed` },
    { label: "Mean time to recover", value: duration(mttr), sub: "detection → verified healthy" },
    { label: "Cost per resolved incident", value: Number.isFinite(cost) ? usd(cost) : "—", sub: "Claude usage, end to end" },
    { label: "Open now", value: String(rows.filter((r) => ACTIVE.includes(r.status)).length), sub: "being worked by the agent" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((i) => (
        <div key={i.label} className="rounded-xl border px-4 py-3.5">
          <p className="micro">{i.label}</p>
          <p className="num mt-2 text-[22px] font-medium tracking-tight">{i.value}</p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">{i.sub}</p>
        </div>
      ))}
    </div>
  );
}

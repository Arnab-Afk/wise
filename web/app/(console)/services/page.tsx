"use client";

import { useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { api, type ServiceHealth } from "@/lib/api";
import { pct } from "@/lib/format";
import { usePoll } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { HealthPill, Pill, Tag } from "@/components/tw/pills";
import { cn } from "@/lib/utils";

interface Edge { src: string; dst: string; calls: number; errors: number }

export default function ServicesPage() {
  const [health, setHealth] = useState<ServiceHealth[] | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  usePoll(() => {
    api<ServiceHealth[]>("/v1/health").then(setHealth).catch(() => {});
    api<{ edges: Edge[] }>("/v1/topology").then((t) => setEdges(t.edges)).catch(() => {});
  }, 4000);

  const rows = useMemo(() => (health ?? []).filter((s) => s.requests || s.baseline_requests || s.alerts?.length || s.error_logs)
    .sort((a, b) => Number(b.status !== "healthy") - Number(a.status !== "healthy") || a.service.localeCompare(b.service)), [health]);
  const unhealthy = rows.filter((r) => r.status !== "healthy").length;

  return (
    <>
      <PageHeader icon={Activity} title="Services">
        {health && <Pill tone={unhealthy ? "bad" : "ok"} dot>{unhealthy ? `${unhealthy} unhealthy` : "all healthy"}</Pill>}
      </PageHeader>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <section className="rounded-xl border">
          <div className="flex items-center border-b px-4 py-2.5">
            <span className="micro">dependency map</span>
            <span className="ml-auto text-[12px] text-muted-foreground">learned from the services&apos; own calls · live error rate</span>
          </div>
          <DependencyMap health={health ?? []} edges={edges} />
        </section>

        <section className="mt-5 overflow-hidden rounded-xl border">
          <div className="border-b px-4 py-2.5"><span className="micro">health against each service&apos;s own baseline · last 30s vs 15 min</span></div>
          {health && !rows.length ? <Empty title="No services reporting yet" /> : (
            <table className="w-full text-[13px]">
              <thead className="bg-sidebar/60 text-left text-[12.5px] text-muted-foreground">
                <tr>{["Service", "Status", "Requests (30s)", "Error rate", "Normal", "p95", "Normal p95", "Commit", "Signals"].map((h) => (
                  <th key={h} className="px-4 py-2 font-normal">{h}</th>))}</tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const hot = s.baseline_error_rate != null && s.error_rate > Math.max(0.05, s.baseline_error_rate * 2);
                  const slow = s.p95_ms && s.baseline_p95_ms && s.p95_ms > s.baseline_p95_ms * 2;
                  return (
                    <tr key={s.service} className="border-t">
                      <td className="px-4 py-2.5 font-mono text-[12.5px]">{s.service}</td>
                      <td className="px-4 py-2.5"><HealthPill status={s.status} /></td>
                      <td className="num px-4 py-2.5">{s.requests}</td>
                      <td className="px-4 py-2.5"><span className={cn("num rounded px-1", hot && "bg-bad-soft text-bad")}>{pct(s.error_rate)}</span></td>
                      <td className="num px-4 py-2.5 text-muted-foreground">{pct(s.baseline_error_rate)}</td>
                      <td className="px-4 py-2.5"><span className={cn("num rounded px-1", slow && "bg-warn-soft text-warn")}>{s.p95_ms ?? "—"}</span></td>
                      <td className="num px-4 py-2.5 text-muted-foreground">{s.baseline_p95_ms ?? "—"}</td>
                      <td className="num px-4 py-2.5 text-muted-foreground">{s.sha || "—"}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {s.alerts?.slice(0, 2).map((a, i) => <Pill key={i} tone={a.severity === "critical" || a.severity === "error" ? "bad" : "warn"}>{a.title.slice(0, 40)}</Pill>)}
                          {s.error_logs ? <Tag>{s.error_logs} error logs</Tag> : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="flex gap-4 border-t px-4 py-2 text-[11.5px] text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-bad-soft" />over 2× normal error rate</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-warn-soft" />over 2× normal latency</span>
          </div>
        </section>
      </div>
    </>
  );
}

/** Layered left-to-right graph: callers on the left, dependencies to the right. */
function DependencyMap({ health, edges }: { health: ServiceHealth[]; edges: Edge[] }) {
  const status = Object.fromEntries(health.map((h) => [h.service, h.status]));
  const nodes = Array.from(new Set(edges.flatMap((e) => [e.src, e.dst])));
  if (!nodes.length) return <Empty title="No calls seen yet" />;
  const depth: Record<string, number> = {};
  const callers = (n: string) => edges.filter((e) => e.dst === n).map((e) => e.src);
  const level = (n: string, seen = new Set<string>()): number => {
    if (depth[n] !== undefined) return depth[n];
    if (seen.has(n)) return 0;
    seen.add(n);
    const c = callers(n);
    return (depth[n] = c.length ? Math.max(...c.map((x) => level(x, seen))) + 1 : 0);
  };
  nodes.forEach((n) => level(n));
  const columns: string[][] = [];
  nodes.sort().forEach((n) => (columns[depth[n]] ??= []).push(n));
  const W = 170, H = 46, GX = 70, GY = 18;
  const tall = Math.max(...columns.map((c) => c.length));
  const width = columns.length * W + (columns.length - 1) * GX + 40;
  const height = tall * H + (tall - 1) * GY + 40;
  const pos: Record<string, { x: number; y: number }> = {};
  columns.forEach((col, ci) => col.forEach((n, ri) => {
    const offset = ((tall - col.length) * (H + GY)) / 2;
    pos[n] = { x: 20 + ci * (W + GX), y: 20 + offset + ri * (H + GY) };
  }));
  const stroke = (s?: string) => s === "erroring" || s === "alerting" ? "var(--bad)" : s === "slow" ? "var(--warn)" : "var(--border)";
  return (
    <div className="overflow-x-auto px-2 py-2">
      <svg width={width} height={height} className="mx-auto block">
        {edges.map((e) => {
          const a = pos[e.src], b = pos[e.dst];
          if (!a || !b) return null;
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
          const bad = status[e.dst] && status[e.dst] !== "healthy";
          return <path key={`${e.src}-${e.dst}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none"
            stroke={bad ? "var(--bad)" : "var(--foreground)"} strokeOpacity={bad ? 0.8 : 0.18} strokeWidth={bad ? 1.6 : 1.2}
            strokeDasharray={bad ? "4 3" : undefined} />;
        })}
        {nodes.map((n) => {
          const p = pos[n], s = status[n];
          const tone = s === "healthy" || !s ? "var(--ok)" : s === "slow" ? "var(--warn)" : s === "silent" ? "var(--muted-foreground)" : "var(--bad)";
          return (
            <g key={n} transform={`translate(${p.x},${p.y})`}>
              <rect width={W} height={H} rx={10} fill="var(--background)" stroke={stroke(s)} strokeWidth={s && s !== "healthy" ? 1.5 : 1} />
              <circle cx={16} cy={H / 2} r={4} fill={tone} />
              <text x={30} y={H / 2 - 3} className="fill-foreground font-mono text-[12px]">{n}</text>
              <text x={30} y={H / 2 + 12} className="fill-muted-foreground text-[11px]">{s ?? "unknown"}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

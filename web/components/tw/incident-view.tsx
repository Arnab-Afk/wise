"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, Bell, BrainCircuit, Bug, Cable, ChartLine, ChevronRight, CircleCheck, Database, FileCode, FileDiff,
  GitCommitHorizontal, HeartPulse, Lightbulb, Link2, ListChecks, MessageSquareText, Network, Pause, Play, Radio,
  RotateCcw, ScrollText, Search, ShieldCheck, SkipBack, SkipForward, Siren, TriangleAlert, UserRoundCog, Workflow,
  Wrench, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { ACTIVE, api, type IncidentDetail, type Step } from "@/lib/api";
import { clock, duration, stamp, tokens, usd } from "@/lib/format";
import { useStream } from "@/hooks/use-stream";
import { Hypotheses, StepBody } from "@/components/tw/step-body";
import { Pill, Ring, SeverityBars, StatusPill, Tag } from "@/components/tw/pills";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

const TOOL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  get_service_health: HeartPulse, get_metrics: ChartLine, search_logs: ScrollText, get_dependencies: Network,
  list_recent_deploys: GitCommitHorizontal, inspect_commit: FileDiff, code_search: Search, code_impact: Workflow,
  explain_failure: Bug, read_code: FileCode, search_memory: BrainCircuit, list_events: Bell, list_sources: Cable,
  query_source: Database,
};
const KIND: Record<string, { icon: React.ComponentType<{ className?: string }>; tag: string }> = {
  detector: { icon: Siren, tag: "detector" }, plan: { icon: ListChecks, tag: "plan" },
  hypotheses: { icon: Lightbulb, tag: "hypotheses" }, action: { icon: Zap, tag: "action" },
  verify: { icon: ShieldCheck, tag: "verify" }, fix: { icon: Wrench, tag: "code fix" },
  environment: { icon: Radio, tag: "update" }, resolve: { icon: CircleCheck, tag: "resolved" },
  escalate: { icon: UserRoundCog, tag: "handover" }, error: { icon: TriangleAlert, tag: "error" },
  tool: { icon: Search, tag: "tool" },
};
const SPEEDS = [1, 2, 4, 8, 16];
const VERBS: Record<string, string> = {
  get_service_health: "Checked service health", get_metrics: "Read metrics", search_logs: "Searched logs",
  get_dependencies: "Mapped dependencies", list_recent_deploys: "Listed recent deploys", inspect_commit: "Inspected commit",
  code_search: "Searched code", code_impact: "Checked blast radius", explain_failure: "Traced error to code",
  read_code: "Read code", search_memory: "Searched past incidents", list_events: "Checked alerts and crashes",
  list_sources: "Listed telemetry sources", query_source: "Queried source",
};

/** "search_logs checkout" -> ["Searched logs", "checkout"] */
function describe(step: Step): [string, string] {
  const tool = step.data?.tool as string | undefined;
  if (step.kind !== "tool" || !tool || !VERBS[tool]) return [step.title, ""];
  const rest = step.title.startsWith(tool) ? step.title.slice(tool.length).trim() : "";
  return [VERBS[tool], rest];
}

export function IncidentView({ id }: { id: string }) {
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState<"timeline" | "evidence" | "raw">("timeline");
  const [cursor, setCursor] = useState<number | null>(null); // replay position in ms; null = show everything
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [now, setNow] = useState(0); // set after mount: Cache Components prerenders this page
  const bottom = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api<IncidentDetail>(`/v1/incidents/${id}`).then((d) => { setIncident(d); setNow(Date.now()); }).catch(() => setMissing(true));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const live = incident ? ACTIVE.includes(incident.status) : false;
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);

  useStream((e) => {
    if (e.type !== "step" || String(e.incident_id) !== id || !e.step) return;
    setIncident((cur) => cur && !cur.steps.some((s) => s.id === e.step.id)
      ? { ...cur, steps: [...cur.steps, e.step] } : cur);
    load(); // pick up status, cost and turns
  });

  const t0 = incident ? new Date(incident.opened_at).getTime() : 0;
  const steps = useMemo(() => incident?.steps ?? [], [incident?.steps]);
  const offsets = useMemo(() => steps.map((s) => Math.max(0, new Date(s.ts).getTime() - t0)), [steps, t0]);
  const end = incident?.resolved_at ? new Date(incident.resolved_at).getTime() - t0
    : live ? now - t0 : (offsets.at(-1) ?? 0);
  const visible = cursor === null ? steps : steps.filter((_, i) => offsets[i] <= cursor);

  useEffect(() => {
    if (!playing) return;
    const tick = setInterval(() => {
      setCursor((c) => {
        const next = (c ?? 0) + 100 * speed;
        if (next >= end) {
          setPlaying(false);
          return null;
        }
        return next;
      });
    }, 100);
    return () => clearInterval(tick);
  }, [playing, speed, end]);

  // Follow new steps while live or replaying.
  useEffect(() => {
    if (playing || (live && cursor === null)) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [visible.length, playing, live, cursor]);

  if (missing) return <div className="p-10 text-muted-foreground">Incident #{id} doesn&apos;t exist.</div>;
  if (!incident) return <DetailSkeleton />;

  const outcome = [...steps].reverse().find((s) => s.kind === "resolve" || s.kind === "escalate");
  const shownOutcome = outcome && visible.includes(outcome) ? outcome : undefined;
  const jump = (dir: 1 | -1) => {
    const at = cursor ?? end;
    const target = dir > 0 ? offsets.find((o) => o > at) : [...offsets].reverse().find((o) => o < at - 1);
    setPlaying(false);
    setCursor(target === undefined ? (dir > 0 ? null : 0) : target);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
        <Link href="/incidents" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Back to incidents">
          <ArrowLeft className="size-4" />
        </Link>
        <SeverityBars severity={incident.severity} />
        <span className="num text-[12.5px] text-muted-foreground">#{incident.id}</span>
        <h1 className="min-w-0 truncate text-[15px] font-medium tracking-tight">{incident.title}</h1>
        <StatusPill status={incident.status} />
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => { navigator.clipboard?.writeText(location.href); toast("Link copied"); }}
            className="flex size-8 items-center justify-center rounded-lg border text-muted-foreground hover:text-foreground" aria-label="Copy link">
            <Link2 className="size-4" />
          </button>
          <div className="flex h-8 items-center rounded-lg border p-0.5">
            {(["timeline", "evidence", "raw"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={cn("h-full rounded-md px-3 text-[13px] capitalize text-muted-foreground", tab === t && "bg-muted text-foreground")}>
                {t}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-[780px] flex-col gap-5 px-6 py-7">
            {tab === "timeline" && (
              <>
                <AlertCard incident={incident} />
                <section className="rounded-xl border">
                  <div className="flex items-center gap-2 border-b px-4 py-2.5">
                    <span className={cn("size-2 rounded-full", live ? "animate-pulse bg-info" : "bg-foreground/70")} />
                    <span className="micro">what happened</span>
                    <span className="num text-[11px] text-muted-foreground">{clock(cursor ?? end)} / {clock(end)}</span>
                    <span className="ml-auto num text-[11px] text-muted-foreground">{visible.length} steps</span>
                  </div>
                  <div className="px-4 pt-3 pb-4">
                    <div className="flex items-center gap-2 pb-2 font-medium">
                      <span className="size-2 bg-foreground" />
                      Incident #{incident.id} response
                    </div>
                    <ol className="ml-[3px] border-l pl-4">
                      {visible.map((s) => <StepRow key={s.id} step={s} offset={new Date(s.ts).getTime() - t0} />)}
                      {live && cursor === null && (
                        <li className="flex items-center gap-2.5 py-2 text-muted-foreground">
                          <span className="flex gap-1">{[0, 1, 2].map((i) => (
                            <span key={i} className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60" style={{ animationDelay: `${i * 120}ms` }} />
                          ))}</span>
                          Agent is {incident.status}…
                        </li>
                      )}
                    </ol>
                  </div>
                </section>
                {shownOutcome && <Outcome step={shownOutcome} />}
                <div ref={bottom} />
              </>
            )}
            {tab === "evidence" && <Evidence incident={incident} outcome={outcome} />}
            {tab === "raw" && (
              <pre className="overflow-x-auto rounded-xl border bg-sidebar/50 p-4 font-mono text-[11.5px] leading-relaxed">
                {JSON.stringify(incident, null, 2)}
              </pre>
            )}
          </div>
        </div>
        <Properties incident={incident} now={now} />
      </div>

      <footer className="flex h-14 shrink-0 items-center gap-3 border-t px-4">
        <button onClick={() => { setPlaying(false); setCursor(0); }} className="rounded-md p-1.5 text-muted-foreground hover:text-foreground" aria-label="Restart replay">
          <RotateCcw className="size-4" />
        </button>
        <button onClick={() => jump(-1)} className="rounded-md p-1.5 text-muted-foreground hover:text-foreground" aria-label="Previous step">
          <SkipBack className="size-4" />
        </button>
        <button onClick={() => { if (!playing && cursor === null) setCursor(0); setPlaying(!playing); }}
          className="flex size-9 items-center justify-center rounded-full bg-foreground text-background" aria-label={playing ? "Pause" : "Replay"}>
          {playing ? <Pause className="size-4 fill-current" /> : <Play className="ml-0.5 size-4 fill-current" />}
        </button>
        <button onClick={() => jump(1)} className="rounded-md p-1.5 text-muted-foreground hover:text-foreground" aria-label="Next step">
          <SkipForward className="size-4" />
        </button>
        <Scrubber offsets={offsets} steps={steps} end={end} cursor={cursor}
          onSeek={(ms) => { setPlaying(false); setCursor(ms >= end ? null : ms); }} />
        <span className="num w-24 text-right text-[12px]">{clock(cursor ?? end)} <span className="text-muted-foreground">/ {clock(end)}</span></span>
        <div className="flex items-center gap-0.5">
          {SPEEDS.map((s) => (
            <button key={s} onClick={() => setSpeed(s)}
              className={cn("num rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground", speed === s && "bg-muted text-foreground")}>
              {s}×
            </button>
          ))}
        </div>
      </footer>
    </div>
  );
}

function Scrubber({ offsets, steps, end, cursor, onSeek }: {
  offsets: number[]; steps: Step[]; end: number; cursor: number | null; onSeek: (ms: number) => void;
}) {
  const at = cursor ?? end;
  return (
    <div className="relative h-6 flex-1 cursor-pointer" onClick={(e) => {
      const r = e.currentTarget.getBoundingClientRect();
      onSeek(Math.round(((e.clientX - r.left) / r.width) * end));
    }}>
      <div className="absolute top-1/2 h-[3px] w-full -translate-y-1/2 rounded-full bg-border" />
      <div className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-foreground" style={{ width: `${end ? (at / end) * 100 : 100}%` }} />
      {steps.map((s, i) => ["action", "verify", "fix", "resolve", "escalate", "hypotheses"].includes(s.kind) && (
        <span key={s.id} title={s.title}
          className={cn("absolute top-1/2 h-2.5 w-[2px] -translate-y-1/2 rounded-full",
            s.kind === "action" || s.kind === "fix" ? "bg-warn" : s.kind === "resolve" || s.kind === "verify" ? "bg-ok" : "bg-foreground/40")}
          style={{ left: `${end ? (offsets[i] / end) * 100 : 0}%` }} />
      ))}
    </div>
  );
}

function StepRow({ step, offset }: { step: Step; offset: number }) {
  const [open, setOpen] = useState(false);
  if (step.kind === "thinking" || step.kind === "note") {
    return (
      <li className="relative flex gap-2.5 py-1.5 text-[13px] text-muted-foreground">
        <MessageSquareText className="mt-0.5 size-3.5 shrink-0 stroke-[1.6]" />
        <span className="min-w-0 flex-1 whitespace-pre-wrap">{step.data?.text ?? step.title}</span>
        <span className="num shrink-0 pt-0.5 text-[11px]">+{clock(offset)}</span>
      </li>
    );
  }
  const meta = KIND[step.kind] ?? KIND.tool;
  const Icon = (step.kind === "tool" && TOOL_ICONS[step.data?.tool]) || meta.icon;
  const expandable = !["resolve", "escalate"].includes(step.kind);
  const failed = Boolean(step.data?.error);
  const emphasis = step.kind === "action" || step.kind === "fix";
  const [label, detail] = describe(step);
  return (
    <li className="relative">
      <button disabled={!expandable} onClick={() => setOpen(!open)}
        className={cn("group flex w-full items-center gap-2.5 rounded-lg py-1.5 pr-1 text-left",
          expandable && "hover:bg-muted/60", emphasis && "font-medium")}>
        <Icon className={cn("size-4 shrink-0 stroke-[1.6]", failed ? "text-bad" : emphasis ? "text-warn" :
          step.kind === "verify" || step.kind === "resolve" ? "text-ok" : "text-foreground/70")} />
        <span className="min-w-0 truncate">
          {label}{detail && <span className="font-mono text-[12px] text-muted-foreground"> · {detail}</span>}
        </span>
        <span className="micro shrink-0 !text-[9.5px]">{step.kind === "tool" ? "tool" : meta.tag}</span>
        {failed && <Pill tone="bad">failed</Pill>}
        <span className="num ml-auto shrink-0 pl-2 text-[11px] text-muted-foreground">+{clock(offset)}</span>
        {expandable && <ChevronRight className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />}
      </button>
      {open && <div className="mt-1 mb-3 ml-6.5"><StepBody step={step} /></div>}
    </li>
  );
}

function AlertCard({ incident }: { incident: IncidentDetail }) {
  return (
    <section className="ml-auto w-full max-w-[600px] rounded-xl border bg-background p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between">
        <span className="micro">alert · detector</span>
        <span className="num text-[11px] text-muted-foreground">{stamp(incident.opened_at)}</span>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {incident.signals.map((s) => (
          <div key={s.service} className="flex flex-wrap items-center gap-2">
            <Tag mono>{s.service}</Tag>
            <span className="font-medium">{s.status}</span>
            {s.requests > 0 && (
              <span className="num text-[12px] text-muted-foreground">
                errors <span className="text-bad">{(s.error_rate * 100).toFixed(0)}%</span> vs {((s.baseline_error_rate ?? 0) * 100).toFixed(0)}% normal
                {s.p95_ms != null && <> · p95 {s.p95_ms} ms vs {s.baseline_p95_ms ?? "—"}</>}
              </span>
            )}
            {s.sha && <Tag mono className="ml-auto">{s.sha}</Tag>}
            {s.alerts?.map((a, i) => <Pill key={i} tone="bad">{a.source}: {a.title}</Pill>)}
          </div>
        ))}
      </div>
    </section>
  );
}

function Outcome({ step }: { step: Step }) {
  const d = step.data ?? {};
  if (step.kind === "escalate") {
    return (
      <section className="rounded-xl border p-5">
        <div className="flex items-center gap-2"><UserRoundCog className="size-4" /><span className="micro">handed over to a human</span></div>
        <p className="mt-3 font-medium">{d.reason}</p>
        <pre className="mt-3 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-foreground/85">{d.handover}</pre>
      </section>
    );
  }
  return (
    <section className="rounded-xl border p-5">
      <div className="flex items-center gap-2 text-ok"><CircleCheck className="size-4" /><span className="micro !text-ok">resolved and verified</span></div>
      <p className="mt-3 text-[15px] font-medium tracking-tight">{d.title}</p>
      {d.summary && <p className="mt-2 leading-relaxed text-foreground/85">{d.summary}</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div><p className="micro">root cause</p><p className="mt-1.5 leading-relaxed">{d.root_cause}</p></div>
        <div><p className="micro">fix</p><p className="mt-1.5 leading-relaxed">{d.fix}</p></div>
      </div>
      {d.lesson && (
        <div className="mt-4 rounded-lg bg-sidebar px-3.5 py-2.5">
          <p className="micro">saved to memory for next time</p>
          <p className="mt-1 text-[13px] leading-relaxed">{d.lesson}</p>
        </div>
      )}
    </section>
  );
}

function Evidence({ incident, outcome }: { incident: IncidentDetail; outcome?: Step }) {
  const evidence: { claim: string; source: string }[] = outcome?.data?.evidence ?? [];
  const hyp = [...incident.steps].reverse().find((s) => s.kind === "hypotheses");
  return (
    <div className="flex flex-col gap-5">
      <section className="rounded-xl border">
        <div className="border-b px-4 py-2.5"><span className="micro">evidence chain</span></div>
        {evidence.length ? (
          <ol className="divide-y">
            {evidence.map((e, i) => (
              <li key={i} className="flex gap-3 px-4 py-2.5">
                <span className="num text-[11px] text-muted-foreground">{i + 1}</span>
                <span className="flex-1">{e.claim}</span>
                <Tag mono className="max-w-[40%] truncate">{e.source}</Tag>
              </li>
            ))}
          </ol>
        ) : <p className="px-4 py-6 text-muted-foreground">No evidence chain recorded yet.</p>}
      </section>
      {hyp && (
        <section className="rounded-xl border p-4">
          <p className="micro mb-3">hypotheses considered</p>
          <Hypotheses items={hyp.data?.input?.hypotheses ?? []} />
        </section>
      )}
      <section className="rounded-xl border">
        <div className="border-b px-4 py-2.5"><span className="micro">changes made to production</span></div>
        {incident.actions.length ? incident.actions.map((a) => (
          <div key={a.id} className="flex items-center gap-3 border-t px-4 py-2.5 first:border-t-0">
            <Zap className="size-4 text-warn" />
            <span className="font-medium">{a.kind}</span>
            {a.target && <Tag mono>{a.target}</Tag>}
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">{String((a.params as any)?.reason ?? "")}</span>
            <Pill tone={a.status === "done" ? "ok" : a.status === "failed" ? "bad" : "info"}>{a.status}</Pill>
          </div>
        )) : <p className="px-4 py-6 text-muted-foreground">No changes made.</p>}
      </section>
    </div>
  );
}

function Properties({ incident, now }: { incident: IncidentDetail; now: number }) {
  const opened = new Date(incident.opened_at).getTime();
  const firstAction = incident.steps.find((s) => s.kind === "action");
  const hyp = [...incident.steps].reverse().find((s) => s.kind === "hypotheses");
  const top = Math.max(0, ...((hyp?.data?.input?.hypotheses ?? []) as any[]).map((h) => h.confidence ?? 0));
  const tools = incident.steps.filter((s) => s.data?.tool).length;
  const rows: [string, React.ReactNode][] = [
    ["Status", <StatusPill key="s" status={incident.status} />],
    ["Severity", <Pill key="v" tone={incident.severity === "critical" ? "bad" : "warn"}>{incident.severity}</Pill>],
    ["Opened", <span key="o" className="num">{stamp(incident.opened_at)}</span>],
    ["First action", <span key="a" className="num">{firstAction ? `+${duration(new Date(firstAction.ts).getTime() - opened)}` : "—"}</span>],
    [incident.resolved_at ? "Time to recover" : "Elapsed", <span key="d" className="num">
      {duration((incident.resolved_at ? new Date(incident.resolved_at).getTime() : now) - opened)}</span>],
    ["Scenario", incident.scenario ? <Pill key="sc">{incident.scenario}</Pill> : "—"],
  ];
  const usage: [string, React.ReactNode][] = [
    ["Model turns", <span key="t" className="num">{incident.turns ?? 0}</span>],
    ["Tool calls", <span key="c" className="num">{tools}</span>],
    ["Tokens", <span key="k" className="num">{tokens(incident.input_tokens)} in · {tokens(incident.output_tokens)} out</span>],
    ["Cost", <span key="u" className="num">{usd(incident.cost_usd)}</span>],
  ];
  return (
    <aside className="hidden w-[300px] shrink-0 overflow-y-auto border-l bg-sidebar/40 px-5 py-5 xl:block">
      <p className="micro mb-3">properties</p>
      <dl className="flex flex-col gap-2.5 text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3"><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>
        ))}
        <div className="flex items-start justify-between gap-3">
          <dt className="text-muted-foreground">Services</dt>
          <dd className="flex flex-wrap justify-end gap-1">{incident.services.map((s) => <Tag key={s} mono>{s}</Tag>)}</dd>
        </div>
      </dl>

      {hyp && (
        <>
          <p className="micro mt-7 mb-3">agent confidence</p>
          <div className="flex items-center gap-3">
            <Ring value={top * 100} size={40} tone={top >= 0.6 ? "ok" : top >= 0.3 ? "warn" : "bad"} />
            <div>
              <p className="font-medium">{top >= 0.75 ? "High" : top >= 0.45 ? "Medium" : "Low"} confidence</p>
              <p className="text-[12px] text-muted-foreground">in its top hypothesis</p>
            </div>
          </div>
          <div className="mt-3 flex flex-col gap-2.5">
            {((hyp.data?.input?.hypotheses ?? []) as any[]).map((h, i) => (
              <div key={i}>
                <div className="flex justify-between gap-3 text-[12px]">
                  <span className="truncate text-muted-foreground">{h.cause}</span>
                  <span className="num">{Math.round((h.confidence ?? 0) * 100)}%</span>
                </div>
                <div className="mt-1 h-1 rounded-full bg-border">
                  <div className="h-1 rounded-full bg-ok" style={{ width: `${(h.confidence ?? 0) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="micro mt-7 mb-3">agent usage</p>
      <dl className="flex flex-col gap-2.5 text-[13px]">
        {usage.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3"><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <p className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        Every model call and tool call in this run is traced in neatlogs.
      </p>
    </aside>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex h-full flex-col">
      <div className="h-14 border-b" />
      <div className="mx-auto flex w-full max-w-[780px] flex-col gap-4 px-6 py-7">
        <div className="ml-auto h-24 w-[600px] max-w-full animate-pulse rounded-xl bg-muted" />
        {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-7 animate-pulse rounded-md bg-muted/70" />)}
      </div>
    </div>
  );
}

export { DetailSkeleton };

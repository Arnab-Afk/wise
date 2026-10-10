"use client";

import { useState } from "react";
import type { Step } from "@/lib/api";
import { pct, short } from "@/lib/format";
import { HealthPill, Pill, Tag } from "@/components/tw/pills";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Diff({ text, max = 40 }: { text: string; max?: number }) {
  const [all, setAll] = useState(false);
  const lines = text.split("\n").filter((l) => !l.startsWith("index "));
  const shown = all ? lines : lines.slice(0, max);
  return (
    <div className="overflow-hidden rounded-lg border bg-sidebar/50">
      <pre className="overflow-x-auto py-2 font-mono text-[11.5px] leading-[1.6]">
        {shown.map((l, i) => (
          <div key={i} className={cn("px-3",
            l.startsWith("+") && !l.startsWith("+++") && "bg-ok-soft text-ok",
            l.startsWith("-") && !l.startsWith("---") && "bg-bad-soft text-bad",
            (l.startsWith("@@") || l.startsWith("diff ")) && "text-info",
            (l.startsWith("+++") || l.startsWith("---")) && "text-muted-foreground")}>
            {l || " "}
          </div>
        ))}
      </pre>
      {lines.length > max && (
        <button onClick={() => setAll(!all)} className="micro w-full border-t py-1.5 hover:bg-muted">
          {all ? "show less" : `show ${lines.length - max} more lines`}
        </button>
      )}
    </div>
  );
}

export function Code({ text, max = 14 }: { text: string; max?: number }) {
  const [all, setAll] = useState(false);
  const lines = String(text).split("\n");
  return (
    <div className="overflow-hidden rounded-lg border bg-sidebar/50">
      <pre className="overflow-x-auto px-3 py-2 font-mono text-[11.5px] leading-[1.6] whitespace-pre-wrap text-foreground/85">
        {(all ? lines : lines.slice(0, max)).join("\n")}
      </pre>
      {lines.length > max && (
        <button onClick={() => setAll(!all)} className="micro w-full border-t py-1.5 hover:bg-muted">
          {all ? "show less" : `show ${lines.length - max} more lines`}
        </button>
      )}
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  return <Code text={typeof value === "string" ? value : JSON.stringify(value, null, 2)} />;
}

/** Error rate over time as small bars, with the running commit changing under them. */
function Sparkline({ rows }: { rows: { t: string; error_rate: number; requests: number; p95_ms: number | null; sha: string | null }[] }) {
  const max = Math.max(0.05, ...rows.map((r) => r.error_rate));
  return (
    <div className="rounded-lg border px-3 pt-3 pb-2">
      <div className="flex h-16 items-end gap-[3px]">
        {rows.map((r, i) => {
          const changed = i > 0 && r.sha && rows[i - 1].sha && r.sha !== rows[i - 1].sha;
          return (
            <div key={i} className="relative flex h-full flex-1 items-end" title={`${r.t} · ${pct(r.error_rate)} errors · p95 ${r.p95_ms ?? "—"} ms · ${short(r.sha)}`}>
              {changed && <span className="absolute inset-y-0 -left-[2px] w-px bg-info" />}
              <span className={cn("w-full rounded-[2px]", r.error_rate > 0.05 ? "bg-bad" : "bg-foreground/15")}
                style={{ height: `${Math.max(3, (r.error_rate / max) * 100)}%` }} />
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[10.5px] text-muted-foreground">
        <span>{rows[0]?.t}</span>
        <span>error rate · blue line = new commit</span>
        <span>{rows.at(-1)?.t}</span>
      </div>
    </div>
  );
}

function HealthTable({ rows }: { rows: any[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-[12.5px]">
        <thead className="bg-sidebar/70 text-left text-muted-foreground">
          <tr>{["service", "status", "errors", "baseline", "p95", "commit"].map((h) => <th key={h} className="px-3 py-1.5 font-normal">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.service} className="border-t">
              <td className="px-3 py-1.5 font-mono">{r.service}</td>
              <td className="px-3 py-1.5"><HealthPill status={r.status} /></td>
              <td className={cn("num px-3 py-1.5", r.error_rate > 0.05 && "text-bad")}>{pct(r.error_rate)}</td>
              <td className="num px-3 py-1.5 text-muted-foreground">{pct(r.baseline_error_rate)}</td>
              <td className="num px-3 py-1.5">{r.p95_ms ?? "—"}<span className="text-muted-foreground"> ms</span></td>
              <td className="num px-3 py-1.5 text-muted-foreground">{short(r.sha)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogGroups({ rows }: { rows: any[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      {rows.map((r, i) => (
        <div key={i} className="rounded-lg border px-3 py-2">
          <div className="flex items-center gap-2">
            <Pill tone={r.level === "critical" || r.level === "error" ? "bad" : "warn"}>{r.n}×</Pill>
            <span className="truncate font-mono text-[12px]">{r.message}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11.5px] text-muted-foreground">
            <Tag mono>{r.service}</Tag>
            {r.route && <Tag mono>{r.route}</Tag>}
            {r.status && <Tag mono>HTTP {r.status}</Tag>}
            {r.sha && <Tag mono>{r.sha}</Tag>}
            {r.source && <Tag>{r.source}</Tag>}
          </div>
          {r.sample_trace && <div className="mt-2"><Code text={r.sample_trace} max={8} /></div>}
        </div>
      ))}
    </div>
  );
}

function Deploys({ rows }: { rows: any[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      {rows.map((d) => (
        <div key={d.id} className="flex items-center gap-3 border-t px-3 py-2 first:border-t-0">
          <Tag mono>{d.service}</Tag>
          <span className="num text-[12px]">{d.sha}</span>
          <span className="min-w-0 flex-1 truncate">{d.message}</span>
          <span className="shrink-0 text-[12px] text-muted-foreground">{d.author} · {d.actor}</span>
          <span className="num shrink-0 text-[12px] text-muted-foreground">{d.minutes_ago}m ago</span>
        </div>
      ))}
    </div>
  );
}

export function Hypotheses({ items }: { items: any[] }) {
  return (
    <div className="flex flex-col gap-2">
      {items.map((h, i) => (
        <div key={i} className="rounded-lg border px-3 py-2.5">
          <div className="flex items-start gap-3">
            <span className="num mt-0.5 text-[11px] text-muted-foreground">H{i + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="font-medium">{h.cause}</p>
              <p className="mt-1 text-[12.5px] text-muted-foreground">{h.evidence}</p>
              {h.test && <p className="mt-1 text-[12.5px]"><span className="micro mr-1.5">test</span>{h.test}</p>}
            </div>
            <div className="w-24 shrink-0">
              <div className="num text-right text-[12px]">{Math.round((h.confidence ?? 0) * 100)}%</div>
              <div className="mt-1 h-1 rounded-full bg-border">
                <div className={cn("h-1 rounded-full", h.confidence >= 0.6 ? "bg-ok" : h.confidence >= 0.3 ? "bg-warn" : "bg-muted-foreground/50")}
                  style={{ width: `${(h.confidence ?? 0) * 100}%` }} />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function KeyValues({ input }: { input: Record<string, any> }) {
  const entries = Object.entries(input ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="inline-flex max-w-full items-baseline gap-1.5 rounded-md border bg-sidebar/50 px-2 py-0.5 text-[12px]">
          <span className="micro">{k}</span>
          <span className="truncate font-mono text-[11.5px]">{typeof v === "string" ? v : JSON.stringify(v)}</span>
        </span>
      ))}
    </div>
  );
}

/** The expanded body of one timeline step. */
export function StepBody({ step }: { step: Step }) {
  const d = step.data ?? {};
  const tool: string | undefined = d.tool;
  const result = d.result;

  if (d.error) {
    return (
      <div className="flex flex-col gap-2">
        <KeyValues input={d.input} />
        <div className="rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 font-mono text-[12px] text-bad">{d.error}</div>
      </div>
    );
  }
  switch (step.kind) {
    case "detector":
      return <HealthTable rows={d.signals ?? []} />;
    case "plan":
      return (
        <div className="flex flex-col gap-2">
          <p><span className="micro mr-1.5">goal</span>{d.input?.goal}</p>
          <ol className="flex flex-col gap-1">
            {(d.input?.steps ?? []).map((s: string, i: number) => (
              <li key={i} className="flex gap-2.5"><span className="num text-muted-foreground">{i + 1}.</span>{s}</li>
            ))}
          </ol>
        </div>
      );
    case "hypotheses":
      return <Hypotheses items={d.input?.hypotheses ?? []} />;
    case "environment":
      return <ul className="list-disc pl-5 text-muted-foreground">{(d.notes ?? []).map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>;
    case "resolve":
    case "escalate":
      return null;
  }
  if (tool === "get_metrics" && Array.isArray(result)) return <><KeyValues input={d.input} /><div className="mt-2"><Sparkline rows={result} /></div></>;
  if ((tool === "get_service_health") && Array.isArray(result)) return <HealthTable rows={result} />;
  if (tool === "verify_recovery" && result?.final) return (
    <div className="flex flex-col gap-2">
      <p className="text-muted-foreground">Watched {d.input?.services?.join(", ")} for {d.input?.seconds ?? 45}s.</p>
      <HealthTable rows={result.final} />
    </div>
  );
  if (tool === "search_logs" && Array.isArray(result)) return result.length ? <LogGroups rows={result} /> : <p className="text-muted-foreground">No matching logs.</p>;
  if (tool === "list_recent_deploys" && Array.isArray(result)) return result.length ? <Deploys rows={result} /> : <p className="text-muted-foreground">No deploys in the window.</p>;
  if (tool === "inspect_commit" && result && typeof result === "object") return (
    <div className="flex flex-col gap-2">
      {result.summary && <Code text={result.summary} max={6} />}
      {result.diff && <Diff text={result.diff} />}
      {result.entire_graph_changes && <><p className="micro">Entire Graph · what changed, by symbol</p><Code text={result.entire_graph_changes} max={10} /></>}
      {result.entire_checkpoint && <><p className="micro">Entire checkpoint · the agent session behind this commit</p><Code text={result.entire_checkpoint} max={10} /></>}
    </div>
  );
  if ((tool === "request_code_fix" || tool === "deploy_fix") && result && typeof result === "object") return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {result.status && <Pill tone={result.status === "ready" ? "ok" : result.status === "failed" ? "bad" : "info"}>{result.status}</Pill>}
        {result.tests_passed != null && <Pill tone={result.tests_passed ? "ok" : "bad"}>tests {result.tests_passed ? "passed" : "failed"}</Pill>}
        {result.commit && <Tag mono>{short(result.commit)}</Tag>}
        {result.now_running && <Tag mono>now running {result.now_running}</Tag>}
        {result.agent && <Tag>{result.agent === "claude" ? "Claude Agent" : "Cursor Agent"}</Tag>}
        {result.branch && <Tag mono>{result.branch}</Tag>}
        {result.entire_checkpoint && <Tag mono>Entire checkpoint {result.entire_checkpoint}</Tag>}
        {result.merged_to_main && <Pill tone="ok">merged to main</Pill>}
      </div>
      {result.summary && <p className="text-[12.5px]">{result.summary}</p>}
      {result.error && <p className="text-[12.5px] text-bad">{result.error}</p>}
      {result.diff && <Diff text={result.diff} />}
      {result.test_output_tail && <><p className="micro">tests, run by Tracewise</p><Code text={result.test_output_tail} max={6} /></>}
    </div>
  );
  if (step.kind === "action") return (
    <div className="flex flex-col gap-2">
      <KeyValues input={d.input} />
      {result && <KeyValues input={result} />}
    </div>
  );
  return (
    <div className="flex flex-col gap-2">
      <KeyValues input={d.input} />
      {result !== undefined && result !== null && <Json value={result} />}
    </div>
  );
}

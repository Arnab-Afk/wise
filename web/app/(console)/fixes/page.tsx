"use client";

import Link from "next/link";
import { useState } from "react";
import { Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { ago, short, usd } from "@/lib/format";
import { usePoll, useStream } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { Pill, Tag } from "@/components/tw/pills";
import { Code, Diff } from "@/components/tw/step-body";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

interface FixJob {
  id: number; incident_id: number | null; provider: string; service: string; branch: string; status: string;
  commit_sha: string | null; checkpoint_id: string | null; tests_passed: boolean | null; cost_usd: number | null;
  created_at: string; finished_at: string | null;
  task?: string; diff?: string; test_output?: string; agent_summary?: string; log?: string; error?: string;
}

const TONE = { ready: "ok", failed: "bad", running: "info", queued: "neutral" } as const;

export default function FixesPage() {
  const [rows, setRows] = useState<FixJob[] | null>(null);
  const [open, setOpen] = useState<FixJob | null>(null);
  const [now, setNow] = useState(0);
  const load = () => api<FixJob[]>("/v1/fix-jobs").then((r) => { setRows(r); setNow(Date.now()); }).catch(() => {});
  usePoll(load, 8000);
  useStream((e) => {
    if (e.type === "fix_job_done") load();
    if (e.type === "fix_job" && open?.id === e.job_id) api<FixJob>(`/v1/fix-jobs/${e.job_id}`).then(setOpen);
  });
  const show = (id: number) => api<FixJob>(`/v1/fix-jobs/${id}`).then(setOpen);

  return (
    <>
      <PageHeader icon={Wrench} title="Code fixes" />
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <p className="mb-4 max-w-2xl text-muted-foreground">
          When the cause is a bug in a change worth keeping, the agent stabilises production first, then asks your connected
          coding agent for a fix with a regression test. Tracewise runs the tests itself before anything ships.
        </p>
        <div className="flex flex-col gap-1.5">
          {rows && !rows.length && <div className="rounded-xl border"><Empty title="No code fixes yet" /></div>}
          {rows?.map((j) => (
            <button key={j.id} onClick={() => show(j.id)}
              className="flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:border-foreground/20">
              <span className="num w-10 text-[12px] text-muted-foreground">#{j.id}</span>
              <Pill tone={TONE[j.status as keyof typeof TONE] ?? "neutral"}>{j.status}</Pill>
              <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{j.branch}</span>
              <Tag>{j.provider === "claude" ? "Claude Agent" : "Cursor Agent"}</Tag>
              {j.tests_passed != null && <Pill tone={j.tests_passed ? "ok" : "bad"}>tests {j.tests_passed ? "pass" : "fail"}</Pill>}
              {j.commit_sha && <Tag mono>{short(j.commit_sha)}</Tag>}
              {j.checkpoint_id && <Tag mono>Entire checkpoint</Tag>}
              <span className="num w-14 text-right text-[12px] text-muted-foreground">{usd(j.cost_usd)}</span>
              <span className="w-16 text-right text-[12px] text-muted-foreground">{ago(j.created_at, now)}</span>
            </button>
          ))}
        </div>
      </div>
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-[680px]">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle>Fix #{open.id} · {open.service}</SheetTitle>
                <div className="flex flex-wrap gap-1.5">
                  <Pill tone={TONE[open.status as keyof typeof TONE] ?? "neutral"}>{open.status}</Pill>
                  {open.tests_passed != null && <Pill tone={open.tests_passed ? "ok" : "bad"}>tests {open.tests_passed ? "pass" : "fail"}</Pill>}
                  {open.commit_sha && <Tag mono>{short(open.commit_sha)}</Tag>}
                  {open.checkpoint_id && <Tag mono>Entire {open.checkpoint_id}</Tag>}
                  {open.incident_id && <Link href={`/incidents/${open.incident_id}`} className="text-[12px] underline">incident #{open.incident_id}</Link>}
                </div>
              </SheetHeader>
              <div className="flex flex-col gap-4 px-4 pb-6">
                {open.agent_summary && <div><p className="micro mb-1.5">agent summary</p><p>{open.agent_summary}</p></div>}
                {open.error && <p className="text-bad">{open.error}</p>}
                {open.diff && <div><p className="micro mb-1.5">diff</p><Diff text={open.diff} max={80} /></div>}
                {open.test_output && <div><p className="micro mb-1.5">tests, run by Tracewise</p><Code text={open.test_output} max={10} /></div>}
                {open.log && <div><p className="micro mb-1.5">agent log</p><Code text={open.log} max={20} /></div>}
                {open.task && <div><p className="micro mb-1.5">task given to the agent</p><Code text={open.task} max={8} /></div>}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}

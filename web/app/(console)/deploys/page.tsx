"use client";

import { useState } from "react";
import { GitCommitHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { usePoll, useStream } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { Pill, Tag } from "@/components/tw/pills";

interface Deploy {
  id: number; service: string; sha: string; prev_sha: string | null; author: string | null; message: string | null;
  actor: string | null; reason: string | null; deployed_at: string;
}

function who(d: Deploy) {
  if (d.actor === "tracewise") return <Pill tone="info">Tracewise</Pill>;
  if (d.actor === "ci") return <Pill>CI</Pill>;
  return <Pill>{d.actor ?? "unknown"}</Pill>;
}

export default function DeploysPage() {
  const [rows, setRows] = useState<Deploy[] | null>(null);
  const [now, setNow] = useState(0);
  const load = () => api<Deploy[]>("/v1/deploys?limit=100").then((r) => { setRows(r); setNow(Date.now()); }).catch(() => {});
  usePoll(load, 10000);
  useStream((e) => { if (e.type === "deploy") load(); });
  return (
    <>
      <PageHeader icon={GitCommitHorizontal} title="Deploys" />
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <section className="overflow-hidden rounded-xl border">
          <div className="border-b px-4 py-2.5"><span className="micro">every change to production · the agent checks these first</span></div>
          {rows && !rows.length && <Empty title="No deploys recorded" />}
          {rows?.map((d) => (
            <div key={d.id} className="flex items-center gap-3 border-t px-4 py-2.5 first:border-t-0">
              <span className="w-20 shrink-0 text-[12px] text-muted-foreground">{ago(d.deployed_at, now)}</span>
              <Tag mono className="w-24 justify-center">{d.service}</Tag>
              <span className="num shrink-0 text-[12px]">
                {d.prev_sha ? <><span className="text-muted-foreground">{d.prev_sha.slice(0, 7)} →</span> </> : null}{d.sha.slice(0, 7)}
              </span>
              <span className="min-w-0 flex-1 truncate" title={d.reason ?? d.message ?? ""}>
                {d.actor === "tracewise" ? <span className="text-muted-foreground">{d.reason ?? "—"}</span> : d.message ?? d.reason ?? "—"}
              </span>
              <span className="hidden shrink-0 text-[12px] text-muted-foreground md:inline">{d.author}</span>
              {who(d)}
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

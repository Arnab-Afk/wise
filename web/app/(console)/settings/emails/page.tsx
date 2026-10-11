"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { canAdmin, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { Pill, Tag } from "@/components/tw/pills";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface Row { id: number; to_email: string; template: string; subject: string; status: string; error: string | null; created_at: string }
interface Full extends Row { html_body: string; text_body: string }
const TONE = { sent: "ok", failed: "bad", queued: "info", skipped: "warn" } as const;

export default function EmailLog() {
  const me = useMe();
  const ws = me?.workspace;
  const [rows, setRows] = useState<Row[] | null>(null);
  const [open, setOpen] = useState<Full | null>(null);
  const [now, setNow] = useState(0);
  const load = useCallback(() => {
    if (ws && canAdmin(me)) api<Row[]>(`/v1/workspaces/${ws.id}/emails`).then((r) => { setRows(r); setNow(Date.now()); }).catch(() => {});
  }, [ws, me]);
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]);

  if (me && !canAdmin(me)) return <p className="text-muted-foreground">Only workspace admins can see the email log.</p>;
  const skipped = rows?.some((r) => r.status === "skipped");
  return (
    <>
      {skipped && (
        <p className="rounded-xl border border-warn/30 bg-warn-soft px-4 py-3 text-[13px] text-warn">
          SMTP isn&apos;t configured, so emails are logged here but not delivered. Set SMTP_HOST, SMTP_USERNAME,
          SMTP_PASSWORD and SMTP_FROM in .env to send them.
        </p>
      )}
      <Section title="Email log" description="Every email Tracewise sent to people in this workspace. Click one to preview it.">
        <div className="divide-y">
          {rows?.length === 0 && <p className="px-5 py-6 text-muted-foreground">No emails yet.</p>}
          {rows?.map((r) => (
            <button key={r.id} onClick={() => api<Full>(`/v1/workspaces/${ws!.id}/emails/${r.id}`).then(setOpen)}
              className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-muted/50">
              <Pill tone={TONE[r.status as keyof typeof TONE] ?? "neutral"}>{r.status}</Pill>
              <span className="min-w-0 flex-1 truncate">{r.subject}</span>
              <Tag mono>{r.template}</Tag>
              <span className="w-44 truncate text-[12.5px] text-muted-foreground">{r.to_email}</span>
              <span className="w-16 text-right text-[12px] text-muted-foreground">{ago(r.created_at, now)}</span>
            </button>
          ))}
        </div>
      </Section>
      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-h-[90vh] overflow-hidden p-0 sm:max-w-[620px]">
          <DialogHeader className="px-5 pt-5">
            <DialogTitle className="pr-6">{open?.subject}</DialogTitle>
            <p className="text-[12.5px] text-muted-foreground">to {open?.to_email}{open?.error ? ` · ${open.error}` : ""}</p>
          </DialogHeader>
          {open && <iframe title="Email preview" srcDoc={open.html_body} sandbox="" className="h-[70vh] w-full border-t bg-white" />}
        </DialogContent>
      </Dialog>
    </>
  );
}

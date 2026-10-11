"use client";

import { useCallback, useEffect, useState } from "react";
import { Hand, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useStream } from "@/hooks/use-stream";
import { useMe } from "@/hooks/use-me";
import { Button } from "@/components/ui/button";

interface Approval { id: number; kind: string; target: string | null; params: Record<string, unknown>; status: string; expires_at: string }
const LABEL: Record<string, string> = { rollback: "Roll back", restart: "Restart", set_flag: "Change flag", deploy_fix: "Deploy code fix" };

/** Pending production actions for this incident: approve or reject them here. */
export function ApprovalBanner({ incidentId }: { incidentId: number }) {
  const me = useMe();
  const [pending, setPending] = useState<Approval[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const load = useCallback(() => {
    api<Approval[]>(`/v1/approvals?incident_id=${incidentId}&pending=true`).then((r) => { setPending(r); setNow(Date.now()); }).catch(() => {});
  }, [incidentId]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  useStream((e) => { if (e.type === "step" && e.incident_id === incidentId) load(); });
  const canAct = me?.role && me.role !== "viewer";

  const decide = async (a: Approval, decision: "approved" | "rejected") => {
    const note = decision === "rejected" ? window.prompt("Why reject? The agent reads this.") ?? undefined : undefined;
    if (decision === "rejected" && note === undefined) return;
    setBusy(a.id);
    try {
      await api(`/v1/approvals/${a.id}/decide`, { method: "POST", body: JSON.stringify({ decision, note }) });
      toast.success(decision === "approved" ? "Approved: the agent is going ahead" : "Rejected: the agent won't do it");
      load();
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };

  if (!pending.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {pending.map((a) => {
        const left = Math.max(0, Math.round((new Date(a.expires_at).getTime() - now) / 60000));
        return (
          <section key={a.id} className="rounded-xl border border-warn/40 bg-warn-soft/60 p-4">
            <div className="flex items-start gap-3">
              <Hand className="mt-0.5 size-4 text-warn" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">Approval needed: {LABEL[a.kind] ?? a.kind} <span className="font-mono">{a.target}</span>
                  {a.params?.to_sha ? <> to <span className="font-mono">{String(a.params.to_sha)}</span></> : null}
                  {a.params?.commit ? <> (commit <span className="font-mono">{String(a.params.commit)}</span>)</> : null}</p>
                {a.params?.reason ? <p className="mt-1 text-[13px] text-foreground/80">{String(a.params.reason)}</p> : null}
                <p className="mt-1.5 text-[12px] text-muted-foreground">The agent is waiting. If nobody answers in about {left} min it won&apos;t do it and will hand over.</p>
              </div>
              {canAct ? (
                <div className="flex shrink-0 gap-2">
                  <Button variant="outline" size="sm" disabled={busy === a.id} onClick={() => decide(a, "rejected")}>Reject</Button>
                  <Button size="sm" disabled={busy === a.id} onClick={() => decide(a, "approved")}>{busy === a.id && <Loader2 className="animate-spin" />}Approve</Button>
                </div>
              ) : <span className="text-[12px] text-muted-foreground">Viewers can&apos;t approve</span>}
            </div>
          </section>
        );
      })}
    </div>
  );
}

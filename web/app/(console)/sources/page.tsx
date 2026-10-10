"use client";

import { useMemo, useState } from "react";
import { Cable, Check, Copy, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { usePoll } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface Source {
  id: number; kind: string; name: string; mode: "pull" | "push"; enabled: boolean; status: string;
  status_detail: string | null; last_polled_at: string | null; last_received_at: string | null; items_received: number;
}
interface Field { name: string; label: string; type: string; required: boolean; default: unknown; help: string | null;
  options: { value: string; label: string }[] | null }
interface PullType { kind: string; label: string; category: string; fields: Field[]; query_language: string }
interface PushType { kind: string; label: string; category: string; endpoint: string; setup: string }

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [types, setTypes] = useState<{ pull: PullType[]; push: PushType[] } | null>(null);
  const [adding, setAdding] = useState(false);
  const [now, setNow] = useState(0);
  const load = () => api<Source[]>("/v1/sources").then((s) => { setSources(s); setNow(Date.now()); }).catch(() => {});
  usePoll(load, 5000);
  usePoll(() => api<{ pull: PullType[]; push: PushType[] }>("/v1/source-types").then(setTypes).catch(() => {}), 600000);

  const toggle = async (s: Source) => {
    await api(`/v1/sources/${s.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !s.enabled }) });
    load();
  };
  const remove = async (s: Source) => {
    if (!confirm(`Remove ${s.name}? Tracewise stops reading from it.`)) return;
    await api(`/v1/sources/${s.id}`, { method: "DELETE" });
    load();
  };

  return (
    <>
      <PageHeader icon={Cable} title="Sources">
        <Button onClick={() => setAdding(true)}><Plus />Connect a source</Button>
      </PageHeader>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <p className="mb-4 max-w-2xl text-muted-foreground">
          Logs, metrics, alerts and deploys from the tools you already run. Tracewise reads some (pull) and receives others
          (push); the agent can also query any pull source live in its own language.
        </p>
        <section className="overflow-hidden rounded-xl border">
          <div className="grid grid-cols-[1.4fr_0.6fr_0.8fr_2fr_0.8fr_auto] gap-3 border-b bg-sidebar/60 px-4 py-2 text-[12.5px] text-muted-foreground">
            <span>Source</span><span>Mode</span><span>Status</span><span>Detail</span><span>Last data</span><span />
          </div>
          {sources && !sources.length && <Empty title="Nothing connected yet">Connect Prometheus, Loki, Datadog, or install the host agent.</Empty>}
          {sources?.map((s) => (
            <div key={s.id} className={cn("grid grid-cols-[1.4fr_0.6fr_0.8fr_2fr_0.8fr_auto] items-center gap-3 border-t px-4 [&>*]:justify-self-start py-2.5 first:border-t-0", !s.enabled && "opacity-50")}>
              <div className="min-w-0">
                <p className="truncate font-medium">{s.name}</p>
                <p className="font-mono text-[11.5px] text-muted-foreground">{s.kind}</p>
              </div>
              <Tag>{s.mode}</Tag>
              <Pill tone={!s.enabled ? "neutral" : s.status === "ok" || s.status === "receiving" ? "ok" : s.status === "failed" ? "bad" : "info"} dot>
                {!s.enabled ? "paused" : s.status}
              </Pill>
              <span className="truncate text-[12.5px] text-muted-foreground" title={s.status_detail ?? ""}>
                {s.status_detail ?? (s.items_received ? `${s.items_received.toLocaleString()} items received` : "—")}
              </span>
              <span className="text-[12px] text-muted-foreground">{ago(s.last_received_at ?? s.last_polled_at, now)}</span>
              <div className="flex gap-1">
                {s.mode === "pull" && <Button variant="ghost" size="sm" onClick={() => toggle(s)}>{s.enabled ? "Pause" : "Resume"}</Button>}
                <Button variant="ghost" size="sm" onClick={() => remove(s)}>Remove</Button>
              </div>
            </div>
          ))}
        </section>
      </div>
      <AddSource open={adding} onOpenChange={setAdding} types={types} onAdded={load} />
    </>
  );
}

function AddSource({ open, onOpenChange, types, onAdded }: {
  open: boolean; onOpenChange: (o: boolean) => void; types: { pull: PullType[]; push: PushType[] } | null; onAdded: () => void;
}) {
  const [picked, setPicked] = useState<{ mode: "pull"; t: PullType } | { mode: "push"; t: PushType } | null>(null);
  const [filter, setFilter] = useState("");
  const close = (o: boolean) => { onOpenChange(o); if (!o) { setPicked(null); setFilter(""); } };
  const groups = useMemo(() => {
    const f = filter.toLowerCase();
    const match = (t: { label: string; kind: string; category: string }) => !f || `${t.label} ${t.kind} ${t.category}`.toLowerCase().includes(f);
    return { pull: types?.pull.filter(match) ?? [], push: types?.push.filter(match) ?? [] };
  }, [types, filter]);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-[760px]">
        <DialogHeader>
          <DialogTitle>{picked ? picked.t.label : "Connect a source"}</DialogTitle>
          <DialogDescription>
            {picked?.mode === "pull" ? "Tracewise checks the credentials, then polls for errors, request metrics and alerts."
              : picked?.mode === "push" ? "Point your tool at Tracewise. It shows up in the list as soon as data arrives."
              : "Pick what you use. Pull: Tracewise reads from it. Push: it sends to Tracewise."}
          </DialogDescription>
        </DialogHeader>
        {!picked && (
          <>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search Prometheus, Datadog, pm2, Kubernetes…"
              className="h-9 rounded-lg border px-3 outline-none focus:border-foreground/30" />
            {(["pull", "push"] as const).map((mode) => (
              <div key={mode}>
                <p className="micro mb-2">{mode === "pull" ? "Tracewise reads from" : "Sends to Tracewise"}</p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {(groups[mode] as (PullType | PushType)[]).map((t) => (
                    <button key={t.kind} onClick={() => setPicked({ mode, t } as never)}
                      className="rounded-lg border px-3 py-2.5 text-left transition-colors hover:border-foreground/30">
                      <p className="font-medium leading-snug">{t.label}</p>
                      <p className="mt-0.5 text-[12px] text-muted-foreground">{t.category}</p>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}
        {picked?.mode === "pull" && <PullForm type={picked.t} onDone={() => { close(false); onAdded(); }} onBack={() => setPicked(null)} />}
        {picked?.mode === "push" && <PushSetup type={picked.t} onBack={() => setPicked(null)} />}
      </DialogContent>
    </Dialog>
  );
}

function PullForm({ type, onDone, onBack }: { type: PullType; onDone: () => void; onBack: () => void }) {
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(type.fields.filter((f) => f.default !== null).map((f) => [f.name, f.default])));
  const [name, setName] = useState(type.kind);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const config = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== "" && v !== null));
      await api("/v1/sources", { method: "POST", body: JSON.stringify({ kind: type.kind, name, config }) });
      toast.success(`${type.label} connected. Checking the credentials now.`);
      onDone();
    } catch (err) {
      toast.error(String((err as Error).message));
    } finally {
      setBusy(false);
    }
  };
  const input = "h-9 w-full rounded-lg border px-3 outline-none focus:border-foreground/30";
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1"><span className="text-[12.5px] font-medium">Name</span>
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} required /></label>
      {type.fields.map((f) => (
        <label key={f.name} className={cn("flex gap-1", f.type === "bool" ? "flex-row items-center gap-2" : "flex-col")}>
          {f.type === "bool" ? (
            <input type="checkbox" checked={Boolean(values[f.name])} onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })} />
          ) : null}
          <span className="text-[12.5px] font-medium">{f.label}{f.required && <span className="text-bad"> *</span>}</span>
          {f.type === "select" ? (
            <select className={input} value={String(values[f.name] ?? "")} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
              {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ) : f.type === "textarea" ? (
            <textarea className="min-h-20 rounded-lg border px-3 py-2 font-mono text-[12px] outline-none focus:border-foreground/30"
              value={String(values[f.name] ?? "")} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} required={f.required} />
          ) : f.type !== "bool" ? (
            <input className={input} type={f.type === "secret" ? "password" : f.type === "int" ? "number" : "text"} autoComplete="off"
              value={String(values[f.name] ?? "")} required={f.required}
              onChange={(e) => setValues({ ...values, [f.name]: f.type === "int" ? Number(e.target.value) : e.target.value })} />
          ) : null}
          {f.help && f.type !== "bool" && <span className="text-[12px] text-muted-foreground">{f.help}</span>}
        </label>
      ))}
      <p className="text-[12px] text-muted-foreground">Secrets are encrypted at rest and never shown again.</p>
      <div className="flex justify-between">
        <Button type="button" variant="ghost" onClick={onBack}>Back</Button>
        <Button type="submit" disabled={busy}>{busy ? "Connecting…" : "Connect"}</Button>
      </div>
    </form>
  );
}

function PushSetup({ type, onBack }: { type: PushType; onBack: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-[12.5px]"><span className="micro">endpoint</span><Tag mono>{type.endpoint}</Tag></div>
      <div className="relative">
        <pre className="max-h-[50vh] overflow-auto rounded-lg border bg-sidebar/60 p-3.5 font-mono text-[12px] leading-relaxed">{type.setup}</pre>
        <button onClick={() => { navigator.clipboard?.writeText(type.setup); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
          className="absolute top-2 right-2 rounded-md border bg-background p-1.5 text-muted-foreground hover:text-foreground" aria-label="Copy">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
      <p className="text-[12px] text-muted-foreground">Replace &lt;ingest key&gt; with your ingest key (TW_INGEST_KEY).</p>
      <div><Button variant="ghost" onClick={onBack}>Back</Button></div>
    </div>
  );
}

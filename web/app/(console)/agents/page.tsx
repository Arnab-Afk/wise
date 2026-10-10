"use client";

import { useState } from "react";
import { Bot, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { usePoll } from "@/hooks/use-stream";
import { Empty, PageHeader } from "@/components/tw/page-header";
import { Pill, Tag } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface Connection {
  id: number; provider: string; label: string; credential_hint: string; model: string | null; is_default: boolean;
  status: string; status_detail: string | null; created_at: string; last_used_at: string | null;
}
interface Provider { id: string; name: string; credential: string; default_model: string | null }

export default function AgentsPage() {
  const [rows, setRows] = useState<Connection[] | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [adding, setAdding] = useState(false);
  const [now, setNow] = useState(0);
  const load = () => api<Connection[]>("/v1/connections").then((r) => { setRows(r); setNow(Date.now()); }).catch(() => {});
  usePoll(load, 4000);
  usePoll(() => api<Provider[]>("/v1/providers").then(setProviders).catch(() => {}), 600000);

  const act = async (path: string, method = "POST") => { await api(path, { method }); load(); };

  return (
    <>
      <PageHeader icon={Bot} title="Coding agents">
        <Button onClick={() => setAdding(true)}><Plus />Connect an agent</Button>
      </PageHeader>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <p className="mb-4 max-w-2xl text-muted-foreground">
          Rollbacks stop the bleeding but throw away the feature. Connect your team&apos;s coding agent and Tracewise hands it the
          fix: its own branch, the evidence, a regression test, and Entire records the session behind every commit.
        </p>
        <div className="flex flex-col gap-2">
          {rows && !rows.length && <div className="rounded-xl border"><Empty title="No coding agent connected">Without one, the agent keeps the rollback and hands the code fix to a human.</Empty></div>}
          {rows?.map((c) => (
            <div key={c.id} className="flex items-center gap-4 rounded-xl border px-4 py-3.5">
              <span className={cn("flex size-9 items-center justify-center rounded-lg font-mono text-[13px] font-semibold",
                c.provider === "claude" ? "bg-[#d97757]/15 text-[#c4613f]" : "bg-foreground text-background")}>
                {c.provider === "claude" ? "C" : "Cu"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{c.label}</p>
                  {c.is_default && <Pill tone="dark">default</Pill>}
                </div>
                <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
                  {c.provider === "claude" ? "Claude Agent" : "Cursor Agent"} · key ••••{c.credential_hint}
                  {c.model && <> · <span className="font-mono">{c.model}</span></>} · {c.last_used_at ? `last fix ${ago(c.last_used_at, now)}` : "not used yet"}
                </p>
              </div>
              <Pill tone={c.status === "ok" ? "ok" : c.status === "failed" ? "bad" : "info"} dot>{c.status === "testing" ? "checking…" : c.status}</Pill>
              {c.status === "failed" && c.status_detail && <Tag className="max-w-60 truncate">{c.status_detail}</Tag>}
              <div className="flex gap-1">
                <Button variant="ghost" size="sm" onClick={() => act(`/v1/connections/${c.id}/test`)}>Re-check</Button>
                {!c.is_default && <Button variant="ghost" size="sm" onClick={() => act(`/v1/connections/${c.id}/default`)}>Make default</Button>}
                <Button variant="ghost" size="sm" onClick={() => confirm(`Disconnect ${c.label}?`) && act(`/v1/connections/${c.id}`, "DELETE")}>Disconnect</Button>
              </div>
            </div>
          ))}
        </div>
        <p className="mt-6 max-w-2xl text-[12px] text-muted-foreground">
          Claude connects with an API key from the Claude Console. Anthropic doesn&apos;t allow third-party products to offer
          claude.ai login. Keys are encrypted at rest; the agent only ever sees its own key inside an isolated worktree.
        </p>
      </div>
      <Connect open={adding} onOpenChange={setAdding} providers={providers} onDone={load} />
    </>
  );
}

function Connect({ open, onOpenChange, providers, onDone }: {
  open: boolean; onOpenChange: (o: boolean) => void; providers: Provider[]; onDone: () => void;
}) {
  const [provider, setProvider] = useState("claude");
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const p = providers.find((x) => x.id === provider);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/v1/connections", { method: "POST", body: JSON.stringify({ provider, api_key: key, label: label || undefined }) });
      toast.success("Connected. Checking the key with the provider now.");
      setKey(""); setLabel(""); onOpenChange(false); onDone();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const input = "h-9 w-full rounded-lg border px-3 outline-none focus:border-foreground/30";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Connect a coding agent</DialogTitle>
          <DialogDescription>Used only to write fixes for incidents, on their own branch.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2">
            {providers.map((x) => (
              <button type="button" key={x.id} onClick={() => setProvider(x.id)}
                className={cn("rounded-lg border px-3 py-2.5 text-left", provider === x.id && "border-foreground")}>
                <p className="font-medium">{x.name}</p>
                <p className="text-[12px] text-muted-foreground">{x.credential}</p>
              </button>
            ))}
          </div>
          <label className="flex flex-col gap-1"><span className="text-[12.5px] font-medium">{p?.credential ?? "API key"}</span>
            <input className={cn(input, "font-mono text-[12.5px]")} type="password" autoComplete="off" value={key}
              onChange={(e) => setKey(e.target.value)} placeholder={provider === "claude" ? "sk-ant-…" : "key_…"} required /></label>
          <label className="flex flex-col gap-1"><span className="text-[12.5px] font-medium">Label</span>
            <input className={input} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={p?.name} /></label>
          <div className="flex justify-end"><Button type="submit" disabled={busy}>{busy ? "Connecting…" : "Connect"}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Shows a freshly created ingest key once, with copy. */
export function KeyReveal({ secret, onClose }: { secret: { name: string; key: string } | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Dialog open={secret !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Your ingest key: {secret?.name}</DialogTitle>
          <DialogDescription>Copy it now. For your security it won&apos;t be shown again; if you lose it, revoke it and make a new one.</DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2 rounded-lg border bg-sidebar px-3 py-2.5">
          <code className="min-w-0 flex-1 font-mono text-[12.5px] break-all">{secret?.key}</code>
          <button onClick={() => { navigator.clipboard?.writeText(secret?.key ?? ""); setCopied(true); }}
            className="rounded-md border bg-background p-1.5" aria-label="Copy key">{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}</button>
        </div>
        <p className="text-[12.5px] text-muted-foreground">
          Use it as <code className="font-mono">x-ingest-key</code> (or bearer token) when sending telemetry, in{" "}
          <code className="font-mono">tracewise login --key</code> for the host agent, and in your shippers&apos; config
          (Sources → Connect a source). Everything sent with it lands in this project only.
        </p>
        <div className="flex justify-end"><Button onClick={onClose}>I&apos;ve copied it</Button></div>
      </DialogContent>
    </Dialog>
  );
}


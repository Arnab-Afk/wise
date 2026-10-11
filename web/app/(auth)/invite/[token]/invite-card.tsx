"use client";

import { use, useEffect, useState } from "react";
import { Loader2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Preview { workspace: string; role: string; email: string; state: string; invited_by: string | null }

export function InviteCard({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [invite, setInvite] = useState<Preview | null>(null);
  const [me, setMe] = useState<{ email: string } | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/tw/v1/invites/preview?token=${encodeURIComponent(token)}`)
      .then(async (r) => (r.ok ? setInvite(await r.json()) : setError((await r.json()).detail)))
      .catch(() => setError("Couldn't load this invitation."));
    fetch("/api/tw/v1/auth/me").then(async (r) => setMe(r.ok ? await r.json() : null)).catch(() => setMe(null));
  }, [token]);

  const accept = async () => {
    setBusy(true); setError("");
    const r = await fetch("/api/tw/v1/invites/accept", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }) });
    const data = await r.json();
    if (!r.ok) { setError(data.detail); setBusy(false); return; }
    try { localStorage.setItem("tw_workspace", String(data.workspace_id)); } catch {}
    location.href = "/incidents";
  };

  const next = encodeURIComponent(`/invite/${token}`);
  return (
    <div className="w-full max-w-[420px] rounded-2xl border bg-background p-8 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <span className="mx-auto flex size-10 items-center justify-center rounded-xl bg-muted"><Users className="size-5" /></span>
      {!invite && !error && <Loader2 className="mx-auto mt-6 size-5 animate-spin text-muted-foreground" />}
      {invite && (
        <>
          <h1 className="mt-4 text-[20px] font-medium tracking-tight">Join {invite.workspace}</h1>
          <p className="mt-1.5 text-muted-foreground">
            {invite.invited_by ?? "A teammate"} invited <span className="text-foreground">{invite.email}</span> as{" "}
            <span className="text-foreground">{invite.role}</span>.
          </p>
          {invite.state !== "pending" ? (
            <p className="mt-6 rounded-lg bg-muted px-3 py-2 text-[13px]">This invitation was {invite.state}. Ask for a new one.</p>
          ) : me === undefined ? null : me ? (
            me.email === invite.email ? (
              <Button size="lg" className="mt-6 h-10 w-full" onClick={accept} disabled={busy}>
                {busy && <Loader2 className="animate-spin" />}Accept and join
              </Button>
            ) : (
              <div className="mt-6 flex flex-col gap-2 text-[13px]">
                <p className="rounded-lg bg-warn-soft px-3 py-2 text-warn">You&apos;re signed in as {me.email}. This invite is for {invite.email}.</p>
                <form action="/api/auth/logout" method="post"><Button type="submit" variant="outline" className="w-full">Sign out and switch</Button></form>
              </div>
            )
          ) : (
            <a href={`/login?next=${next}`} className="mt-6 flex h-10 items-center justify-center rounded-lg bg-foreground font-medium text-background">
              Sign in as {invite.email} to accept
            </a>
          )}
        </>
      )}
      {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-[12.5px] text-bad">{error}</p>}
    </div>
  );
}

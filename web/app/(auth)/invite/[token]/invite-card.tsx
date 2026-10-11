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
    window.location.assign("/overview");
  };

  const next = encodeURIComponent(`/invite/${token}`);
  return (
    <div>
      <span className="flex size-11 items-center justify-center rounded-xl border border-black/10 bg-white"><Users className="size-5" /></span>
      {!invite && !error && <Loader2 className="mx-auto mt-6 size-5 animate-spin text-muted-foreground" />}
      {invite && (
        <>
          <h1 className="display mt-6 text-[44px] text-black">Join {invite.workspace}</h1>
          <p className="mt-3 text-[15px] text-black/60">
            {invite.invited_by ?? "A teammate"} invited <span className="text-foreground">{invite.email}</span> as{" "}
            <span className="text-foreground">{invite.role}</span>.
          </p>
          {invite.state !== "pending" ? (
            <p className="mt-6 rounded-lg bg-muted px-3 py-2 text-[13px]">This invitation was {invite.state}. Ask for a new one.</p>
          ) : me === undefined ? null : me ? (
            me.email === invite.email ? (
              <Button size="lg" className="mt-8 h-11 w-full" onClick={accept} disabled={busy}>
                {busy && <Loader2 className="animate-spin" />}Accept and join
              </Button>
            ) : (
              <div className="mt-6 flex flex-col gap-2 text-[13px]">
                <p className="rounded-lg bg-warn-soft px-3 py-2 text-warn">You&apos;re signed in as {me.email}. This invite is for {invite.email}.</p>
                <form action="/api/auth/logout" method="post"><Button type="submit" variant="outline" className="w-full">Sign out and switch</Button></form>
              </div>
            )
          ) : (
            <a href={`/signup?next=${next}&email=${encodeURIComponent(invite.email)}`} className="mt-8 flex h-11 items-center justify-center rounded-lg bg-[#1c1b19] font-medium text-white">
              Continue as {invite.email}
            </a>
          )}
        </>
      )}
      {error && <p className="mt-4 rounded-lg bg-bad-soft px-3 py-2 text-[12.5px] text-bad">{error}</p>}
    </div>
  );
}

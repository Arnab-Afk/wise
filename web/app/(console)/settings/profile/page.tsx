"use client";

import { useEffect, useState } from "react";
import { Monitor } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { refreshMe, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { GitHubIcon, GoogleIcon } from "@/components/tw/brand";
import { Pill } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Session { id: number; method: string; ip: string | null; user_agent: string | null; created_at: string; last_seen_at: string; current: boolean }

const NOTIFY = [
  ["all", "Every incident", "Resolutions and escalations, with root cause and fix."],
  ["escalations", "Only when I'm needed", "When the agent hands an incident to a human."],
  ["none", "None", "Check the console yourself."],
];

function device(ua: string | null) {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : ua.split(" ")[0];
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

export default function ProfileSettings() {
  const me = useMe();
  const [draft, setName] = useState<string | null>(null); // null until edited
  const [sessions, setSessions] = useState<Session[]>([]);
  const [now, setNow] = useState(0);
  const loadSessions = () => api<Session[]>("/v1/auth/sessions").then((s) => { setSessions(s); setNow(Date.now()); }).catch(() => {});
  useEffect(() => { loadSessions(); }, []);

  const save = (body: object, msg: string) =>
    api("/v1/auth/me", { method: "PATCH", body: JSON.stringify(body) }).then(refreshMe).then(() => toast.success(msg))
      .catch((e) => toast.error(e.message));

  if (!me) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  const name = draft ?? me.name ?? "";
  return (
    <>
      <Section title="Profile">
        <form className="flex items-end gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault(); save({ name }, "Saved"); }}>
          <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Name</span>
            <input className="h-9 rounded-lg border px-3 outline-none focus:border-foreground/40" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="flex flex-1 flex-col gap-1.5"><span className="text-[12.5px] font-medium">Email</span>
            <input className="h-9 rounded-lg border px-3 text-muted-foreground" value={me.email} disabled /></label>
          <Button type="submit" variant="outline" className="h-9" disabled={name === (me.name ?? "")}>Save</Button>
        </form>
      </Section>

      <Section title="Incident emails" description="What Tracewise emails you about.">
        <div className="grid gap-2 p-4 sm:grid-cols-3">
          {NOTIFY.map(([value, label, hint]) => (
            <button key={value} onClick={() => save({ notify_incidents: value }, "Notifications updated")}
              className={cn("rounded-lg border px-3.5 py-3 text-left transition-colors hover:border-foreground/30",
                me.notify_incidents === value && "border-foreground")}>
              <p className="font-medium">{label}</p>
              <p className="mt-0.5 text-[12px] text-muted-foreground">{hint}</p>
            </button>
          ))}
        </div>
      </Section>

      <Section title="Sign-in methods" description="Email codes always work. Google and GitHub sign in to the account with the same verified email.">
        <div className="divide-y">
          {[["google", "Google", <GoogleIcon key="g" />], ["github", "GitHub", <GitHubIcon key="h" />]].map(([id, label, icon]) => (
            <div key={id as string} className="flex items-center gap-3 px-5 py-3">
              {icon}<span className="flex-1">{label}</span>
              {me.linked.includes(id as string) ? <Pill tone="ok" dot>linked</Pill> : <Pill>not linked</Pill>}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Sessions" description="Devices signed in to your account."
        action={sessions.length > 1 ? <Button variant="outline" size="sm" onClick={() =>
          Promise.all(sessions.filter((s) => !s.current).map((s) => api(`/v1/auth/sessions/${s.id}`, { method: "DELETE" })))
            .then(loadSessions).then(() => toast.success("Signed out other sessions"))}>Sign out others</Button> : null}>
        <div className="divide-y">
          {sessions.map((s) => (
            <div key={s.id} className="flex items-center gap-3 px-5 py-3">
              <Monitor className="size-4 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{device(s.user_agent)}{s.current && <Pill tone="ok" className="ml-2">this device</Pill>}</p>
                <p className="text-[12.5px] text-muted-foreground">via {s.method} · {s.ip ?? "unknown IP"} · active {ago(s.last_seen_at, now)}</p>
              </div>
              {!s.current && <Button variant="ghost" size="sm" onClick={() => api(`/v1/auth/sessions/${s.id}`, { method: "DELETE" }).then(loadSessions)}>Sign out</Button>}
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}

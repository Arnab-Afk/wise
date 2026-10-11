"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { canAdmin, useMe } from "@/hooks/use-me";
import { Section } from "@/components/tw/section";
import { SlackIcon } from "@/components/tw/slack-icon";
import { DiscordIcon } from "@/components/tw/discord-icon";
import { Pill } from "@/components/tw/pills";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Route { project_id: number; project: string; slug: string; channel_id: string | null; channel_name: string | null; events: string[] | null }
interface Status { configured: boolean; installed: { team_name: string; team_id: string; installed_by: string | null; created_at: string } | null;
  routes: Route[]; events: string[]; manifest_url: string }
interface Channel { id: string; name: string; private: boolean; member: boolean }
const EVENT_LABEL: Record<string, string> = { opened: "Incident opened", approval: "Approvals", action: "Agent actions", fix: "Code fixes", resolved: "Resolved", escalated: "Needs a human" };

export default function Integrations() {
  const me = useMe();
  const admin = canAdmin(me);
  const [status, setStatus] = useState<Status | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => {
    api<Status>("/v1/slack/status").then((s) => {
      setStatus(s);
      if (s.installed && admin) api<Channel[]>("/v1/slack/channels").then(setChannels).catch((e) => toast.error(e.message));
    }).catch(() => {});
  }, [admin]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("slack");
    if (p === "connected") toast.success("Slack connected");
    else if (p === "error") toast.error("Slack didn't finish connecting. Try again.");
  }, []);

  const run = async (k: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(k);
    try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(""); }
  };
  const save = (r: Route, patch: Partial<Route>) => {
    const next = { ...r, ...patch };
    const ch = channels.find((c) => c.id === next.channel_id);
    return run(`r${r.project_id}`, () => api(`/v1/slack/routes/${r.project_id}`, { method: "PUT",
      body: JSON.stringify({ channel_id: next.channel_id, channel_name: ch?.name ?? next.channel_name, events: next.events ?? status?.events }) }), "Saved");
  };

  if (!status) return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  return (
    <>
      <Section title="Slack" description="Each incident becomes a live thread in your channel: what broke, what the agent did, and how it ended."
        action={<SlackIcon className="size-6" />}>
        {!status.configured ? (
          <div className="flex flex-col gap-3 px-5 py-4 text-[13.5px]">
            <p>The Tracewise Slack app isn&apos;t set up on this server yet. It takes two minutes:</p>
            <ol className="ml-5 list-decimal space-y-1.5 text-muted-foreground">
              <li><a href={status.manifest_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-foreground underline">Create the app from this manifest <ExternalLink className="size-3" /></a>{" "}(everything is pre-filled: bot, /tracewise command, buttons).</li>
              <li>In the app&apos;s <em>Basic Information</em>, copy the Client ID, Client Secret and Signing Secret.</li>
              <li>Put them in the server&apos;s <code className="font-mono">.env</code> as <code className="font-mono">SLACK_CLIENT_ID</code>, <code className="font-mono">SLACK_CLIENT_SECRET</code>, <code className="font-mono">SLACK_SIGNING_SECRET</code> and restart.</li>
            </ol>
          </div>
        ) : !status.installed ? (
          <div className="flex items-center gap-4 px-5 py-4">
            <p className="flex-1 text-[13.5px] text-muted-foreground">Connect your Slack workspace, then choose a channel for each project.</p>
            {admin ? (
              <button onClick={() => run("install", async () => { const { url } = await api<{ url: string }>("/v1/slack/install-url"); window.location.href = url; })}
                className="flex h-10 items-center gap-2.5 rounded-lg border bg-background px-4 font-medium hover:border-foreground/30">
                <SlackIcon />Add to Slack
              </button>
            ) : <Pill>Ask an admin to connect Slack</Pill>}
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 border-b px-5 py-3">
              <Pill tone="ok" dot>connected</Pill>
              <span className="text-[13.5px]">to <span className="font-medium">{status.installed.team_name}</span>{status.installed.installed_by ? ` by ${status.installed.installed_by}` : ""}</span>
              {admin && <Button variant="ghost" size="sm" className="ml-auto text-bad" onClick={() => confirm("Disconnect Slack? Incidents stop being posted.") &&
                run("rm", () => api("/v1/slack/installation", { method: "DELETE" }), "Slack disconnected")}>Disconnect</Button>}
            </div>
            <div className="divide-y">
              {status.routes.map((r) => {
                const events = r.events ?? status.events;
                return (
                  <div key={r.project_id} className="flex flex-col gap-3 px-5 py-4">
                    <div className="flex items-center gap-3">
                      <span className="w-40 truncate font-mono text-[13px]">{r.slug}</span>
                      <select disabled={!admin} className="h-9 min-w-56 rounded-lg border bg-background px-3 text-[13px]" value={r.channel_id ?? ""}
                        onChange={(e) => save(r, { channel_id: e.target.value || null })}>
                        <option value="">Not posted to Slack</option>
                        {channels.map((c) => <option key={c.id} value={c.id}>{c.private ? "🔒 " : "#"}{c.name}</option>)}
                      </select>
                      {busy === `r${r.project_id}` && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                      {r.channel_id && admin && <Button variant="outline" size="sm" className="ml-auto"
                        onClick={() => run(`t${r.project_id}`, () => api(`/v1/slack/test/${r.project_id}`, { method: "POST" }), `Test message sent to #${r.channel_name}`)}>
                        Send test</Button>}
                    </div>
                    {r.channel_id && (
                      <div className="flex flex-wrap gap-1.5 pl-[172px]">
                        {status.events.map((ev) => {
                          const on = events.includes(ev);
                          return <button key={ev} disabled={!admin} onClick={() => save(r, { events: on ? events.filter((x) => x !== ev) : [...events, ev] })}
                            className={cn("flex h-7 items-center gap-1 rounded-full border px-3 text-[12.5px]", on ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30")}>
                            {on && <Check className="size-3" />}{EVENT_LABEL[ev] ?? ev}</button>;
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="border-t px-5 py-3 text-[12.5px] text-muted-foreground">
              Private channel? Invite <span className="font-mono">@Tracewise</span> to it first. In any channel, try <span className="font-mono">/tracewise status</span>.
            </p>
          </>
        )}
      </Section>
      <DiscordSection admin={admin} />
    </>
  );
}

interface DStatus { configured: boolean; installed: { guild_name: string; guild_id: string; installed_by: string | null } | null;
  routes: Route[]; events: string[]; setup: { interactions_url: string; redirect_url: string } }

function DiscordSection({ admin }: { admin: boolean }) {
  const [status, setStatus] = useState<DStatus | null>(null);
  const [channels, setChannels] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => {
    api<DStatus>("/v1/discord/status").then((s) => {
      setStatus(s);
      if (s.installed && admin) api<{ id: string; name: string }[]>("/v1/discord/channels").then(setChannels).catch((e) => toast.error(e.message));
    }).catch(() => {});
  }, [admin]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("discord");
    if (p === "connected") toast.success("Discord connected");
    else if (p === "error") toast.error("Discord didn't finish connecting. Try again.");
  }, []);
  const run = async (k: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(k);
    try { await fn(); if (ok) toast.success(ok); load(); } catch (e) { toast.error((e as Error).message); } finally { setBusy(""); }
  };
  const save = (r: Route, patch: Partial<Route>) => {
    const next = { ...r, ...patch };
    const ch = channels.find((c) => c.id === next.channel_id);
    return run(`r${r.project_id}`, () => api(`/v1/discord/routes/${r.project_id}`, { method: "PUT",
      body: JSON.stringify({ channel_id: next.channel_id, channel_name: ch?.name ?? next.channel_name, events: next.events ?? status?.events }) }), "Saved");
  };
  if (!status) return null;
  return (
    <Section title="Discord" description="Each incident is posted with a live status card and a thread for the agent's updates."
      action={<DiscordIcon className="size-6" />}>
      {!status.configured ? (
        <div className="flex flex-col gap-3 px-5 py-4 text-[13.5px]">
          <p>The Tracewise Discord app isn&apos;t set up on this server yet:</p>
          <ol className="ml-5 list-decimal space-y-1.5 text-muted-foreground">
            <li>In the <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-foreground underline">Discord Developer Portal <ExternalLink className="size-3" /></a>, create an application named Tracewise.</li>
            <li><em>General Information</em>: set <strong>Interactions Endpoint URL</strong> to <code className="font-mono text-[12px]">{status.setup.interactions_url}</code>.</li>
            <li><em>OAuth2</em>: add the redirect <code className="font-mono text-[12px]">{status.setup.redirect_url}</code>. <em>Bot</em>: reset and copy the token.</li>
            <li>Put <code className="font-mono">DISCORD_APP_ID</code>, <code className="font-mono">DISCORD_PUBLIC_KEY</code>, <code className="font-mono">DISCORD_CLIENT_SECRET</code> and <code className="font-mono">DISCORD_BOT_TOKEN</code> in the server&apos;s <code className="font-mono">.env</code> and restart.</li>
          </ol>
        </div>
      ) : !status.installed ? (
        <div className="flex items-center gap-4 px-5 py-4">
          <p className="flex-1 text-[13.5px] text-muted-foreground">Add the Tracewise bot to your Discord server, then choose a channel for each project.</p>
          {admin ? (
            <button onClick={() => run("install", async () => { const { url } = await api<{ url: string }>("/v1/discord/install-url"); window.location.href = url; })}
              className="flex h-10 items-center gap-2.5 rounded-lg border bg-background px-4 font-medium hover:border-foreground/30"><DiscordIcon />Add to Discord</button>
          ) : <Pill>Ask an admin to connect Discord</Pill>}
        </div>
      ) : (
        <>
          <div className="flex items-center gap-3 border-b px-5 py-3">
            <Pill tone="ok" dot>connected</Pill>
            <span className="text-[13.5px]">to <span className="font-medium">{status.installed.guild_name}</span>{status.installed.installed_by ? ` by ${status.installed.installed_by}` : ""}</span>
            {admin && <Button variant="ghost" size="sm" className="ml-auto text-bad" onClick={() => confirm("Remove the bot from your Discord server?") &&
              run("rm", () => api("/v1/discord/installation", { method: "DELETE" }), "Discord disconnected")}>Disconnect</Button>}
          </div>
          <div className="divide-y">
            {status.routes.map((r) => {
              const events = r.events ?? status.events;
              return (
                <div key={r.project_id} className="flex flex-col gap-3 px-5 py-4">
                  <div className="flex items-center gap-3">
                    <span className="w-40 truncate font-mono text-[13px]">{r.slug}</span>
                    <select disabled={!admin} className="h-9 min-w-56 rounded-lg border bg-background px-3 text-[13px]" value={r.channel_id ?? ""}
                      onChange={(e) => save(r, { channel_id: e.target.value || null })}>
                      <option value="">Not posted to Discord</option>
                      {channels.map((c) => <option key={c.id} value={c.id}>#{c.name}</option>)}
                    </select>
                    {busy === `r${r.project_id}` && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                    {r.channel_id && admin && <Button variant="outline" size="sm" className="ml-auto"
                      onClick={() => run(`t${r.project_id}`, () => api(`/v1/discord/test/${r.project_id}`, { method: "POST" }), `Test message sent to #${r.channel_name}`)}>Send test</Button>}
                  </div>
                  {r.channel_id && (
                    <div className="flex flex-wrap gap-1.5 pl-[172px]">
                      {status.events.map((ev) => {
                        const on = events.includes(ev);
                        return <button key={ev} disabled={!admin} onClick={() => save(r, { events: on ? events.filter((x) => x !== ev) : [...events, ev] })}
                          className={cn("flex h-7 items-center gap-1 rounded-full border px-3 text-[12.5px]", on ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:border-foreground/30")}>
                          {on && <Check className="size-3" />}{EVENT_LABEL[ev] ?? ev}</button>;
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <p className="border-t px-5 py-3 text-[12.5px] text-muted-foreground">Try <span className="font-mono">/tracewise view:status</span> in any channel. Approvals open Tracewise, where the approver&apos;s identity is checked.</p>
        </>
      )}
    </Section>
  );
}

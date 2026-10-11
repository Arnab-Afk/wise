"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Activity, Bot, Cable, Check, ChevronDown, ChevronsUpDown, GitCommitHorizontal, LayoutGrid, LogOut, Plus,
  Settings, Siren, Users, UsersRound, Wrench,
} from "lucide-react";
import { api, ACTIVE, switchTo, type Incident } from "@/lib/api";
import { usePoll, useStream } from "@/hooks/use-stream";
import { canAdmin, useMe } from "@/hooks/use-me";
import { Avatar } from "@/components/tw/avatar";
import { NewProjectDialog } from "@/components/tw/new-project";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: React.ComponentType<{ className?: string }>; match?: string };
const TOP: Item[] = [{ href: "/overview", label: "Overview", icon: LayoutGrid }];
const PROJECT: Item[] = [
  { href: "/incidents", label: "Incidents", icon: Siren },
  { href: "/services", label: "Services", icon: Activity },
  { href: "/deploys", label: "Deploys", icon: GitCommitHorizontal },
  { href: "/fixes", label: "Code fixes", icon: Wrench },
  { href: "/sources", label: "Sources", icon: Cable },
];
const PEOPLE: Item[] = [
  { href: "/members", label: "Members", icon: Users },
  { href: "/teams", label: "Teams", icon: UsersRound },
];
const WORKSPACE: Item[] = [
  { href: "/agents", label: "Coding agents", icon: Bot },
  { href: "/settings/project", label: "Settings", icon: Settings, match: "/settings" },
];

function NavItem({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={cn("flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/70 transition-colors hover:bg-black/[0.04] hover:text-foreground",
      active && "bg-black/[0.055] font-medium text-foreground")}>
      <Icon className="size-4 stroke-[1.6]" />{item.label}
    </Link>
  );
}

function Group({ label, items, path, children }: { label?: React.ReactNode; items: Item[]; path: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      {label && <div className="px-2.5 pt-3 pb-1 text-[12px] text-muted-foreground">{label}</div>}
      {children}
      {items.map((i) => <NavItem key={i.href} item={i} active={path === i.href || path.startsWith(`${i.match ?? i.href}/`) || path === i.match} />)}
    </div>
  );
}

export function SidebarNav() {
  const path = usePathname();
  return (
    <nav className="flex flex-col gap-1">
      <Group items={TOP} path={path} />
      <Group label="Project" items={PROJECT} path={path}><ProjectPicker /></Group>
      <Group label="People" items={PEOPLE} path={path} />
      <Group label="Workspace" items={WORKSPACE} path={path} />
    </nav>
  );
}

export function NavFallback() {
  return <nav className="flex flex-col gap-1 px-1 pt-1">{[...TOP, ...PROJECT, ...PEOPLE, ...WORKSPACE].map((i) => <div key={i.href} className="h-8" />)}</nav>;
}

function useClickAway(open: boolean, close: () => void) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) close(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open, close]);
  return box;
}

function ProjectPicker() {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const box = useClickAway(open, () => setOpen(false));
  if (!me?.project) return null;
  return (
    <div ref={box} className="relative mb-1">
      <button onClick={() => setOpen(!open)} className="flex h-8 w-full items-center gap-2 rounded-lg border bg-background px-2.5 text-left text-[13px] hover:border-foreground/20">
        <span className="size-1.5 rounded-full bg-ok" />
        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{me.project.slug}</span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute top-full right-0 left-0 z-50 mt-1 rounded-xl border bg-background p-1.5 shadow-lg">
          {me.projects.map((p) => (
            <button key={p.id} onClick={() => switchTo(me.workspace?.id ?? null, p.id)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-muted">
              <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{p.slug}</span>
              {p.id === me.project?.id && <Check className="size-3.5" />}
            </button>
          ))}
          {canAdmin(me) && (
            <button onClick={() => { setOpen(false); setCreating(true); }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground">
              <Plus className="size-3.5" />New project
            </button>
          )}
        </div>
      )}
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

interface WorkspaceRow { id: number; name: string; role: string; members: number }

export function WorkspaceBadge() {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<WorkspaceRow[]>([]);
  const box = useClickAway(open, () => setOpen(false));
  const toggle = () => {
    if (!open) api<WorkspaceRow[]>("/v1/workspaces").then(setRows).catch(() => {});
    setOpen(!open);
  };
  const ws = me?.workspace;
  return (
    <div ref={box} className="relative flex items-center gap-1.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background">T</span>
      <span className="text-muted-foreground/50">/</span>
      <button onClick={toggle} className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-black/[0.04]">
        <Avatar name={ws?.name ?? "?"} size={20} />
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{ws?.name ?? "…"}</span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute top-full left-6 z-50 mt-1 w-64 rounded-xl border bg-background p-1.5 shadow-lg">
          <p className="px-2 pt-1 pb-1.5 text-[12px] text-muted-foreground">Workspaces</p>
          {rows.map((w) => (
            <button key={w.id} onClick={() => switchTo(w.id, null)} className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left hover:bg-muted">
              <Avatar name={w.name} size={26} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px]">{w.name}</span>
                <span className="block text-[12px] text-muted-foreground">{w.role[0].toUpperCase() + w.role.slice(1)}, {w.members} {w.members === 1 ? "member" : "members"}</span>
              </span>
              {w.id === ws?.id && <Check className="size-3.5" />}
            </button>
          ))}
          <div className="my-1.5 border-t" />
          <Link href="/onboarding?new=1" className="flex items-center gap-2.5 rounded-md px-2 py-2 text-[13.5px] hover:bg-muted">
            <Plus className="size-4" />Create workspace
          </Link>
        </div>
      )}
    </div>
  );
}

/** How many incidents the agent is working on right now, in this project. */
export function LiveActivity() {
  const [active, setActive] = useState<number | null>(null);
  const load = () => api<Incident[]>("/v1/incidents?limit=50")
    .then((rows) => setActive(rows.filter((r) => ACTIVE.includes(r.status)).length)).catch(() => {});
  usePoll(load, 10000);
  useStream((e) => { if (e.type === "incident_opened" || e.type === "step") load(); });
  return (
    <Link href="/incidents" className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-foreground/70 hover:bg-black/[0.04]">
      <span className={cn("size-2 rounded-full", active ? "animate-pulse bg-bad" : "bg-ok")} />
      {active ? "Agent working" : "All clear"}
      {active ? <span className="num ml-auto rounded-md bg-bad-soft px-1.5 text-[11px] text-bad">{active}</span> : null}
    </Link>
  );
}

/** Who's signed in, with a way out. */
export function UserChip() {
  const me = useMe();
  if (!me) return <div className="h-11" />;
  return (
    <div className="flex items-center gap-2 px-1 py-1">
      <Link href="/settings/profile" className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md hover:opacity-80">
        <Avatar name={me.name || me.email} src={me.avatar_url} size={32} />
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-medium">{me.name || me.email.split("@")[0]}</span>
          <span className="block truncate text-[12px] text-muted-foreground">{me.email}</span>
        </span>
      </Link>
      <form action="/api/auth/logout" method="post">
        <button type="submit" className="rounded-md p-1.5 text-muted-foreground hover:bg-black/[0.04] hover:text-foreground" aria-label="Sign out" title="Sign out">
          <LogOut className="size-4" />
        </button>
      </form>
    </div>
  );
}

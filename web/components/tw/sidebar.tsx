"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Activity, Bot, Cable, Check, ChevronDown, ChevronsUpDown, GitCommitHorizontal, LayoutGrid, LogOut, Monitor, Moon, Plus,
  Settings, Siren, Sun, UserRound, Users, UsersRound, Wrench,
} from "lucide-react";
import { useTheme } from "next-themes";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
    <Link href={item.href} className={cn("flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] text-foreground/70 transition-colors hover:bg-foreground/[0.05] hover:text-foreground",
      active && "bg-foreground/[0.07] font-medium text-foreground")}>
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

function ProjectPicker() {
  const me = useMe();
  const [creating, setCreating] = useState(false);
  if (!me?.project) return null;
  return (
    <div className="mb-1">
      <DropdownMenu>
        <DropdownMenuTrigger className="flex h-8 w-full items-center gap-2 rounded-lg border bg-background px-2.5 text-left text-[13px] outline-none hover:border-foreground/20">
          <span className="size-1.5 rounded-full bg-ok" />
          <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{me.project.slug}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-56 p-1.5">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Projects in {me.workspace?.name}</DropdownMenuLabel>
            {me.projects.map((p) => (
              <DropdownMenuItem key={p.id} onClick={() => switchTo(me.workspace?.id ?? null, p.id)} className="py-1.5">
                <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{p.slug}</span>
                {p.id === me.project?.id && <Check className="size-3.5" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          {canAdmin(me) && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setCreating(true)} className="py-1.5 text-muted-foreground"><Plus />New project</DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

interface WorkspaceRow { id: number; name: string; role: string; members: number }

export function WorkspaceBadge() {
  const me = useMe();
  const router = useRouter();
  const [rows, setRows] = useState<WorkspaceRow[]>([]);
  const ws = me?.workspace;
  return (
    <div className="flex items-center gap-1.5">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-foreground font-mono text-[13px] font-semibold text-background">T</span>
      <span className="text-muted-foreground/50">/</span>
      <DropdownMenu onOpenChange={(open) => { if (open) api<WorkspaceRow[]>("/v1/workspaces").then(setRows).catch(() => {}); }}>
        <DropdownMenuTrigger className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left outline-none hover:bg-foreground/[0.05]">
          <Avatar name={ws?.name ?? "?"} size={20} />
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{ws?.name ?? "…"}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-72 p-1.5" align="start">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
            {rows.map((w) => (
              <DropdownMenuItem key={w.id} onClick={() => switchTo(w.id, null)} className="gap-2.5 py-2">
                <Avatar name={w.name} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px]">{w.name}</span>
                  <span className="block text-[12px] text-muted-foreground">{w.role[0].toUpperCase() + w.role.slice(1)}, {w.members} {w.members === 1 ? "member" : "members"}</span>
                </span>
                {w.id === ws?.id && <Check className="size-3.5" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => router.push("/onboarding?new=1")} className="gap-2.5 py-2"><Plus />Create workspace</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
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
  // Only shown while the agent is working an incident; nothing when all is well.
  if (!active) return null;
  return (
    <Link href="/incidents" className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-foreground/70 hover:bg-foreground/[0.05]">
      <span className="size-2 animate-pulse rounded-full bg-bad" />
      Agent working
      <span className="num ml-auto rounded-md bg-bad-soft px-1.5 text-[11px] text-bad">{active}</span>
    </Link>
  );
}

/** Who's signed in: profile, theme and sign out. */
export function UserChip() {
  const me = useMe();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  if (!me) return <div className="h-11" />;
  const name = me.name || me.email.split("@")[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-lg px-1.5 py-1.5 text-left outline-none hover:bg-foreground/[0.05]">
        <Avatar name={me.name || me.email} src={me.avatar_url} size={32} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{name}</span>
          <span className="block truncate text-[12px] text-muted-foreground">{me.email}</span>
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-60 p-1.5">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1.5">
            <span className="block truncate text-[13px] font-medium text-foreground">{name}</span>
            <span className="block truncate text-[12px] font-normal">{me.email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/settings/profile")} className="py-1.5"><UserRound />Profile settings</DropdownMenuItem>
        <DropdownMenuItem onClick={() => router.push("/settings/workspace")} className="py-1.5"><Settings />Workspace settings</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Theme</DropdownMenuLabel>
          <div className="grid grid-cols-3 gap-1 px-1 pb-1">
            {([["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]] as const).map(([value, Icon, label]) => (
              <button key={value} onClick={() => setTheme(value)}
                className={cn("flex flex-col items-center gap-1 rounded-md border py-1.5 text-[11.5px] text-muted-foreground transition-colors hover:text-foreground",
                  theme === value && "border-foreground/40 bg-muted text-foreground")}>
                <Icon className="size-3.5" />{label}
              </button>
            ))}
          </div>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" className="py-1.5" onClick={() => {
          // A full load after sign-out, so nothing from the old session stays in memory.
          fetch("/api/auth/logout", { method: "POST" }).finally(() => { window.location.href = "/login"; });
        }}><LogOut />Log out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

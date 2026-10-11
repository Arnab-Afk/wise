"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface Me {
  id: number; email: string; name: string | null; avatar_url: string | null; notify_incidents: string;
  workspace: { id: number; name: string; slug: string; role: string } | null; role: string | null;
  workspaces: { id: number; name: string; slug: string; role: string }[]; linked: string[];
}

let cache: Me | null = null;
const listeners = new Set<(m: Me) => void>();

export function refreshMe() {
  return api<Me>("/v1/auth/me").then((m) => { cache = m; listeners.forEach((l) => l(m)); return m; });
}

/** The signed-in user and their current workspace (shared across components). */
export function useMe() {
  const [me, setMe] = useState<Me | null>(cache);
  useEffect(() => {
    listeners.add(setMe);
    if (!cache) refreshMe().catch(() => {});
    return () => { listeners.delete(setMe); };
  }, []);
  return me;
}

export const canAdmin = (me: Me | null) => me?.role === "owner" || me?.role === "admin";

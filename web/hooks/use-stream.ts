"use client";

import { useEffect, useRef } from "react";
import { API } from "@/lib/api";

export type StreamEvent = { type: string; [key: string]: any }; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Subscribes to Tracewise's live event stream (new steps, incidents, deploys, alerts). */
export function useStream(onEvent: (event: StreamEvent) => void) {
  const handler = useRef(onEvent);
  useEffect(() => {
    handler.current = onEvent;
  });
  useEffect(() => {
    const source = new EventSource(`${API}/v1/stream`);
    const types = ["step", "incident_opened", "deploy", "fix_job", "fix_job_done", "source_event"];
    const listener = (e: MessageEvent) => {
      try {
        handler.current(JSON.parse(e.data));
      } catch {}
    };
    types.forEach((t) => source.addEventListener(t, listener));
    return () => source.close();
  }, []);
}

/** Polls a loader, and re-runs it early when a matching stream event arrives. */
export function usePoll(load: () => void, ms: number) {
  const fn = useRef(load);
  useEffect(() => {
    fn.current = load;
  });
  useEffect(() => {
    fn.current();
    const t = setInterval(() => fn.current(), ms);
    return () => clearInterval(t);
  }, [ms]);
}

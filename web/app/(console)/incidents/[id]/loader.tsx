"use client";

import { use } from "react";
import { IncidentView } from "@/components/tw/incident-view";

export function IncidentLoader({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <IncidentView id={id} />;
}

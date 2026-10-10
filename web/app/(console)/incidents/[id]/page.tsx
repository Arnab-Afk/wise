import { Suspense } from "react";
import { DetailSkeleton } from "@/components/tw/incident-view";
import { IncidentLoader } from "./loader";

export default function IncidentPage({ params }: PageProps<"/incidents/[id]">) {
  // The id is only known at request time, so it's read inside Suspense (Cache Components).
  return (
    <Suspense fallback={<DetailSkeleton />}>
      <IncidentLoader params={params} />
    </Suspense>
  );
}

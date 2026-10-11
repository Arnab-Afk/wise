import { Suspense } from "react";
import { InviteCard } from "./invite-card";

export default function InvitePage({ params }: PageProps<"/invite/[token]">) {
  return (
    <Suspense fallback={<div className="h-[300px] w-full max-w-[420px] rounded-2xl border bg-background" />}>
      <InviteCard params={params} />
    </Suspense>
  );
}

import { Suspense } from "react";
import { AuthShell } from "@/components/tw/auth-shell";
import { InviteCard } from "./invite-card";

export default function InvitePage({ params }: PageProps<"/invite/[token]">) {
  return (
    <AuthShell>
      <Suspense><InviteCard params={params} /></Suspense>
    </AuthShell>
  );
}

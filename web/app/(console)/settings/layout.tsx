import { Suspense } from "react";
import { Settings } from "lucide-react";
import { PageHeader } from "@/components/tw/page-header";
import { SettingsTabs } from "./tabs";

export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return (
    <>
      <PageHeader icon={Settings} title="Settings">
        <Suspense fallback={null}><SettingsTabs /></Suspense>
      </PageHeader>
      <div className="flex-1 overflow-y-auto px-5 py-6"><div className="mx-auto flex max-w-[860px] flex-col gap-5">{children}</div></div>
    </>
  );
}

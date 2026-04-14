import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { Bell, CheckCircle2, AlertCircle } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Notifications"
        title="Your notification inbox"
        description="Loading your messages and updates..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Unread" value="--" icon={Bell} />
        <StatCard label="Read" value="--" icon={CheckCircle2} />
        <StatCard label="Alerts" value="--" icon={AlertCircle} />
      </section>
    </AppPage>
  );
}

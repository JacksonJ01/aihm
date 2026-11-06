import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { Users, UserPlus, Activity } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Friends"
        title="Your training network"
        description="Loading your friends list and activity..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Friends" value="--" icon={Users} />
        <StatCard label="Pending requests" value="--" icon={UserPlus} />
        <StatCard label="Recent activity" value="--" icon={Activity} />
      </section>
    </AppPage>
  );
}

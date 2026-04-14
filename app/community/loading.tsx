import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { Users, MessageSquare, Trophy } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Community"
        title="Connect with other athletes"
        description="Loading community posts, challenges, and discussion threads..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Community members" value="--" icon={Users} />
        <StatCard label="Active posts" value="--" icon={MessageSquare} />
        <StatCard label="Active challenges" value="--" icon={Trophy} />
      </section>
    </AppPage>
  );
}

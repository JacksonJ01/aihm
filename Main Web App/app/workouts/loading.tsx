import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { Activity, Clock3, Sparkles } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Workout studio"
        title="Loading workout studio"
        description="Fetching your workout sessions and tracking data..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Recent score" value="--" icon={Activity} />
        <StatCard label="Sessions logged" value="--" icon={Clock3} />
        <StatCard label="Current state" value="Loading" icon={Sparkles} />
      </section>
    </AppPage>
  );
}

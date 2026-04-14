import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { TrendingUp, Calendar, Zap } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Progress"
        title="Track your training journey"
        description="Loading your progress metrics and analytics..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Current streak" value="--" icon={Zap} />
        <StatCard label="Progress this month" value="--" icon={TrendingUp} />
        <StatCard label="Last updated" value="--" icon={Calendar} />
      </section>
    </AppPage>
  );
}

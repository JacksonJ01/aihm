import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { User, Settings, BarChart3 } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Profile"
        title="Your training profile"
        description="Loading your personal profile and preferences..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Total workouts" value="--" icon={BarChart3} />
        <StatCard label="Account status" value="--" icon={User} />
        <StatCard label="Settings" value="--" icon={Settings} />
      </section>
    </AppPage>
  );
}

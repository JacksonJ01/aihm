import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { Search, Grid3x3, Zap } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Browse programs"
        title="Explore training programs"
        description="Loading available programs and recommendations..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Available programs" value="--" icon={Grid3x3} />
        <StatCard label="Featured" value="--" icon={Zap} />
        <StatCard label="Total enrolled" value="--" icon={Search} />
      </section>
    </AppPage>
  );
}

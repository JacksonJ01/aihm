import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";
import { BookOpen, CheckCircle2, Clock3 } from "lucide-react";

export default function Loading() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Programs"
        title="Loading programs"
        description="Fetching available training programs..."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Enrolled programs" value="--" icon={BookOpen} />
        <StatCard label="Completed" value="--" icon={CheckCircle2} />
        <StatCard label="In progress" value="--" icon={Clock3} />
      </section>
    </AppPage>
  );
}

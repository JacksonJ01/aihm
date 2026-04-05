import { Compass, Layers3, TimerReset } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { ProgramBrowser } from "@/components/app/program-browser";
import { getBrowseProgramsData } from "@/lib/site-data";

const selectionGuide = [
  {
    title: "Pick by training need",
    description: "Choose the program that solves the current gap in your week, not the one that sounds hardest.",
  },
  {
    title: "Respect weekly capacity",
    description: "Sessions per week matter more than ambition. Select something you can actually repeat.",
  },
  {
    title: "Commit long enough to learn",
    description: "Programs only become useful once the app can compare one week of work against the next.",
  },
];

export default async function BrowseProgramsPage() {
  const programs = await getBrowseProgramsData();
  const featuredCount = programs.data.filter((program) => program.featured).length;

  return (
    <AppPage>
      <PageHero
        eyebrow="Program library"
        title="Browse structured plans that give your training week a real shape."
        description="Browse plans by focus, training load, and duration to find a program that fits the week ahead."
        actions={[
          { href: "/programs", label: "Current programs", secondary: true },
          { href: "/workouts", label: "Start a workout" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={programs.source}
              viewerState={programs.viewerState}
              viewerEmail={programs.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-white/75 px-5 py-5">
              {/* Internal note: this card should explain the library at a glance, not instruct the operator. */}
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Program overview</div>
              <div className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
                <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">Focus areas: Strength, Mobility, Conditioning</div>
                <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">Difficulty bands: Beginner to Advanced</div>
                <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">Program length: 3 to 6 weeks</div>
              </div>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Programs available" value={String(programs.data.length).padStart(2, "0")} detail="The library is designed around plans with a clear weekly cadence." icon={Layers3} />
        <StatCard label="Featured plans" value={String(featuredCount).padStart(2, "0")} detail="Recommended starting points when you want strong defaults instead of guesswork." icon={Compass} />
        <StatCard label="Typical cycle" value="3-6 wks" detail="Short enough to stay responsive, long enough to measure progress over time." icon={TimerReset} />
      </section>

      <SectionCard
        eyebrow="Available now"
        title="Programs built for different kinds of momentum"
        description="Each program card tells you what it is for, how often you will train, and why it belongs in the library."
      >
        <ProgramBrowser programs={programs.data} />
      </SectionCard>

      <SectionCard
        eyebrow="How to choose"
        title="A good program is one you can keep repeating."
        description="A few quick reference points make it easier to compare plans and choose one that fits your week."
      >
        <div className="grid gap-4 lg:grid-cols-3">
          {selectionGuide.map((item) => (
            <article key={item.title} className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
              <h3 className="text-xl font-semibold tracking-[-0.03em] text-foreground">{item.title}</h3>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{item.description}</p>
            </article>
          ))}
        </div>
      </SectionCard>
    </AppPage>
  );
}

import { ArrowUpRight, Flame, Layers2, Target } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  InlineLink,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { formatLongDate, getProgramsData } from "@/lib/site-data";
import { Suspense } from "react";

function progressWidth(value: number) {
  return `${Math.max(6, Math.min(100, value))}%`;
}

function ProgramsPageFallback() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Current programs"
        title="Keep active plans visible enough that the next session never feels buried."
        description="Loading your active programs, weekly load, and current streaks."
      />
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Plans active" value="--" detail="Loading active training plans." icon={Layers2} />
        <StatCard label="Weekly load" value="--" detail="Loading weekly completed and target sessions." icon={Target} />
        <StatCard label="Top streak" value="--" detail="Loading current adherence streaks." icon={Flame} />
      </section>
    </AppPage>
  );
}

async function ProgramsPageContent() {
  const programs = await getProgramsData();
  const activePrograms = programs.data.filter((program) => program.status.toLowerCase() !== "completed");
  const weeklyCompleted = programs.data.reduce((sum, program) => sum + program.weeklyCompleted, 0);
  const weeklyTarget = programs.data.reduce((sum, program) => sum + program.weeklyTarget, 0);
  const topStreak = programs.data.length ? Math.max(...programs.data.map((program) => program.streakDays)) : 0;

  return (
    <AppPage>
      <PageHero
        eyebrow="Current programs"
        title="Keep active plans visible enough that the next session never feels buried."
        description="Your current programs page should answer three things fast: what is active, what is next, and whether the week is still on track."
        actions={[
          { href: "/browsePrograms", label: "Browse more programs", secondary: true },
          { href: "/workouts", label: "Start next session" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={programs.source}
              viewerState={programs.viewerState}
              viewerEmail={programs.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">This week</div>
              <div className="mt-4 text-4xl font-semibold tracking-[-0.04em]">{weeklyCompleted}/{weeklyTarget}</div>
              <p className="mt-2 text-sm leading-6 text-white/70">Completed sessions against your active weekly target across all current plans.</p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Plans active" value={String(activePrograms.length).padStart(2, "0")} detail="Enough variety to build momentum without scattering focus." icon={Layers2} />
        <StatCard label="Weekly load" value={`${weeklyCompleted}/${weeklyTarget}`} detail="A single read on whether your training week is still achievable." icon={Target} />
        <StatCard label="Top streak" value={`${topStreak} days`} detail="The longest current adherence run across your active plans." icon={Flame} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_340px]">
        <SectionCard
          eyebrow="Active list"
          title="Programs in motion"
          description="Each card surfaces progress, next session timing, and whether the plan still fits the current week."
        >
          <div className="space-y-4">
            {programs.data.length ? (
              programs.data.map((program) => (
                <article key={program.id} className="rounded-[26px] border border-black/10 bg-white/72 px-5 py-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="max-w-2xl">
                      <div className="flex flex-wrap gap-2">
                        <span className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-accent-foreground">
                          {program.focus}
                        </span>
                        <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                          {program.status}
                        </span>
                      </div>
                      <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{program.title}</h2>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {program.completedSessions} sessions completed so far. Next session scheduled for {formatLongDate(program.nextSession)}.
                      </p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[280px] lg:grid-cols-1">
                      <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Progress</div>
                        <div className="mt-2 text-lg font-semibold text-foreground">{program.progressPercent}%</div>
                      </div>
                      <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Weekly target</div>
                        <div className="mt-2 text-lg font-semibold text-foreground">{program.weeklyCompleted}/{program.weeklyTarget}</div>
                      </div>
                      <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Streak</div>
                        <div className="mt-2 text-lg font-semibold text-foreground">{program.streakDays} days</div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 h-3 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: progressWidth(program.progressPercent) }} />
                  </div>
                </article>
              ))
            ) : (
              <div className="rounded-[24px] border border-dashed border-black/10 bg-background/60 px-5 py-5 text-sm leading-6 text-muted-foreground">
                No active programs yet. Use Browse Programs to add the first structured plan.
              </div>
            )}
          </div>
        </SectionCard>

        <div className="grid gap-6">
          <SectionCard
            eyebrow="Next actions"
            title="Keep the handoff tight"
            description="These quick links make the programs page feel operational instead of informational."
          >
            <div className="space-y-4">
              <div className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
                <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">Start the next planned session</div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">Move directly into the workout tool when you are ready to execute.</p>
                <div className="mt-4">
                  <InlineLink href="/workouts">Open workout studio</InlineLink>
                </div>
              </div>
              <div className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
                <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">Compare against progress</div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">Check whether the current plan is producing stronger scores, better consistency, or both.</p>
                <div className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-primary">
                  <ArrowUpRight className="h-4 w-4" />
                  <span>Progress is one click away</span>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      </section>
    </AppPage>
  );
}

export default function ProgramsPage() {
  return (
    <Suspense fallback={<ProgramsPageFallback />}>
      <ProgramsPageContent />
    </Suspense>
  );
}

import { Activity, CalendarRange, Gauge, Trophy } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { formatShortDate, getWorkoutSessionsData } from "@/lib/site-data";
import { Suspense } from "react";

function trendHeight(score: number) {
  return `${Math.max(18, Math.min(100, score))}%`;
}

function ProgressPageFallback() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Progress dashboard"
        title="Turn completed sessions into a view you can actually steer from."
        description="Loading recent workout trends, streaks, and highlights."
      />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Average score" value="--" detail="Loading recent movement quality." icon={Gauge} />
        <StatCard label="Minutes logged" value="--" detail="Loading recent training volume." icon={CalendarRange} />
        <StatCard label="Live streak" value="--" detail="Loading recent consistency." icon={Trophy} />
        <StatCard label="Focus areas" value="--" detail="Loading recent training mix." icon={Activity} />
      </section>
    </AppPage>
  );
}

async function ProgressPageContent() {
  const sessions = await getWorkoutSessionsData();
  const totalMinutes = sessions.data.reduce((sum, session) => sum + session.duration_minutes, 0);
  const averageScore = sessions.data.length
    ? Math.round(sessions.data.reduce((sum, session) => sum + session.score, 0) / sessions.data.length)
    : 0;
  const streak = sessions.data.slice(0, 3).length;
  const strongestSession = sessions.data.length
    ? sessions.data.reduce((best, session) => (session.score > best.score ? session : best), sessions.data[0])
    : null;
  const longestSession = sessions.data.length
    ? sessions.data.reduce(
        (currentLongest, session) =>
          session.duration_minutes > currentLongest.duration_minutes ? session : currentLongest,
        sessions.data[0],
      )
    : null;

  return (
    <AppPage>
      <PageHero
        eyebrow="Progress dashboard"
        title="Turn completed sessions into a view you can actually steer from."
        description="Track recent workload, movement quality, and consistency from one clear progress view."
        actions={[
          { href: "/programs", label: "View current programs", secondary: true },
          { href: "/workouts", label: "Start another session" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={sessions.source}
              viewerState={sessions.viewerState}
              viewerEmail={sessions.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-white/75 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Recent pattern</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                Scores are strongest when shorter recovery and mobility sessions stay in the week instead of being skipped first.
              </p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Average score" value={`${averageScore}%`} detail="Movement quality averaged across your most recent logged sessions." icon={Gauge} />
        <StatCard label="Minutes logged" value={`${totalMinutes}`} detail="Recent training volume, including short recovery and mobility work." icon={CalendarRange} />
        <StatCard label="Live streak" value={`${streak} sessions`} detail="A simple read on whether progress is still active instead of stale." icon={Trophy} />
        <StatCard label="Focus areas" value={`${new Set(sessions.data.map((session) => session.focus_area)).size}`} detail="A snapshot of variety in your recent training mix." icon={Activity} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard
          eyebrow="Session trend"
          title="Quality over the last few workouts"
          description="The chart is intentionally simple: enough to show whether form and effort are trending well without turning the page into analytics clutter."
        >
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-end">
            <div className="grid h-[260px] grid-cols-4 gap-4 rounded-[28px] border border-black/10 bg-white/70 px-5 py-6">
              {sessions.data.length ? (
                sessions.data.slice(0, 4).reverse().map((session) => (
                  <div key={session.id} className="flex flex-col items-center justify-end gap-3">
                    <div className="flex w-full items-end justify-center rounded-t-[18px] bg-[linear-gradient(180deg,rgba(237,104,41,0.88),rgba(237,104,41,0.42))]" style={{ height: trendHeight(session.score) }} />
                    <div className="text-center text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {formatShortDate(session.completed_at)}
                    </div>
                    <div className="text-sm font-semibold text-foreground">{session.score}</div>
                  </div>
                ))
              ) : (
                <div className="col-span-4 flex items-center justify-center rounded-[24px] border border-dashed border-black/10 bg-background/60 px-4 py-6 text-center text-sm leading-6 text-muted-foreground">
                  Your first logged sessions will populate the progress trend here.
                </div>
              )}
            </div>

            <div className="space-y-3">
              {sessions.data.length ? (
                sessions.data.slice(0, 3).map((session) => (
                  <article key={session.id} className="rounded-[24px] border border-black/10 bg-background/70 px-4 py-4">
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{session.focus_area}</div>
                    <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-foreground">{session.title}</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{session.notes}</p>
                  </article>
                ))
              ) : null}
            </div>
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Milestones"
          title="What the numbers are saying"
          description="Recent highlights make it easier to see where the strongest sessions are coming from."
        >
          <div className="space-y-3">
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-4 py-4">
              <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">Most stable session</div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{strongestSession?.title ?? "Start tracking sessions to unlock this highlight."}</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-4 py-4">
              <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">Biggest workload day</div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{longestSession?.title ?? "This appears after your first longer workout is recorded."}</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-4 py-4">
              <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">Best use of recovery</div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">The highest score this week came from a lighter session, which usually means readiness is improving.</p>
            </div>
          </div>
        </SectionCard>
      </section>
    </AppPage>
  );
}

export default function ProgressPage() {
  return (
    <Suspense fallback={<ProgressPageFallback />}>
      <ProgressPageContent />
    </Suspense>
  );
}

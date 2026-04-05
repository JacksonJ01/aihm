import { Activity, CheckCircle2, Clock3, Sparkles } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { formatLongDate, getWorkoutSessionsData } from "@/lib/site-data";

import WorkoutsSession from "./workoutsSession";

const prepChecklist = [
  "The session works best with enough floor space for stepping, hinging, and rotation without clipping the frame.",
  "The camera view is most stable when the full body remains visible before the first rep begins.",
  "Pose guidance adds the most value during technique work, while timer-led sessions can stay camera-free.",
];

export default async function Page() {
  const sessions = await getWorkoutSessionsData();
  const latestSession = sessions.data[0];
  const averageScore = sessions.data.length
    ? Math.round(sessions.data.reduce((sum, session) => sum + session.score, 0) / sessions.data.length)
    : 0;

  return (
    <AppPage>
      <PageHero
        eyebrow="Workout studio"
        title="Start training with a setup that makes the next rep obvious."
        description="The workout studio keeps preparation, live tracking, and recent session context in one place so the training flow stays clear from start to finish."
        actions={[
          { href: "/progress", label: "Review progress", secondary: true },
          { href: "/programs", label: "Open current programs" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={sessions.source}
              viewerState={sessions.viewerState}
              viewerEmail={sessions.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white shadow-[0_24px_60px_rgba(15,23,42,0.24)]">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Latest session</div>
              {latestSession ? (
                <>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.04em]">{latestSession.title}</div>
                  <p className="mt-3 text-sm leading-6 text-white/70">{latestSession.notes}</p>
                  <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium text-white/80">
                    <span className="rounded-full bg-white/10 px-3 py-1">{latestSession.focus_area}</span>
                    <span className="rounded-full bg-white/10 px-3 py-1">{latestSession.duration_minutes} min</span>
                    <span className="rounded-full bg-white/10 px-3 py-1">Score {latestSession.score}</span>
                  </div>
                </>
              ) : (
                <p className="mt-3 text-sm leading-6 text-white/70">
                  No sessions have been recorded yet. Start one from this page and the latest result will appear here.
                </p>
              )}
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Recent score" value={`${averageScore}%`} detail="Average movement quality across the latest recorded sessions." icon={Activity} />
        <StatCard label="Sessions logged" value={String(sessions.data.length).padStart(2, "0")} detail="Recent workouts kept visible so your next decision has context." icon={Clock3} />
        <StatCard label="Current state" value="Ready" detail="The live tracking view is prepared for a guided session whenever you start the camera." icon={Sparkles} />
      </section>

      <section className="space-y-6">
        <SectionCard
          eyebrow="Before you begin"
          title="Session setup"
          description="A compact overview of the conditions that keep the live session stable and readable across devices."
        >
          <div className="grid gap-3 lg:grid-cols-3">
            {prepChecklist.map((item) => (
              <div key={item} className="flex gap-3 rounded-2xl border border-black/10 bg-white/70 px-4 py-4">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                <p className="text-sm leading-6 text-muted-foreground">{item}</p>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Live session"
          title="Train from one focused workspace"
          description="The live workout area keeps controls, feed state, and camera guidance together so the page behaves like a session tool instead of a generic content block."
        >
          <WorkoutsSession />
        </SectionCard>

        <SectionCard
          eyebrow="Session history"
          title="Recent workouts"
          description="Recent sessions stay visible for quick context around workload, effort, and movement quality."
        >
          <div className="grid gap-4 xl:grid-cols-2">
            {sessions.data.length ? (
              sessions.data.slice(0, 4).map((session) => (
                <article key={session.id} className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="max-w-2xl">
                      <div className="text-xl font-semibold tracking-[-0.03em] text-foreground">{session.title}</div>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">{session.notes}</p>
                    </div>
                    <div className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-accent-foreground">
                      {session.effort}
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2 text-xs font-medium text-muted-foreground">
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{session.focus_area}</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{session.duration_minutes} min</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{formatLongDate(session.completed_at)}</span>
                  </div>
                </article>
              ))
            ) : (
              <div className="xl:col-span-2 rounded-[22px] border border-dashed border-black/10 bg-background/60 px-4 py-5 text-sm leading-6 text-muted-foreground">
                Your workout history will appear here after the first recorded session.
              </div>
            )}
          </div>
        </SectionCard>
      </section>
    </AppPage>
  );
}
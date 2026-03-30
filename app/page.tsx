"use client";

import Link from "next/link";

export default function Home() {
  const highlights = [
    {
      title: "Live movement feedback",
      description:
        "Run body tracking during training and see your session respond to how you move, not just what you click.",
    },
    {
      title: "Programs with structure",
      description:
        "Move from daily workouts into repeatable plans that give the app a clear coaching role.",
    },
    {
      title: "Progress you can read",
      description:
        "Bring workouts, adherence, and future pose quality into one place so the app feels cumulative.",
    },
  ];

  const actions = [
    {
      href: "/workouts",
      title: "Start a guided workout",
      description: "Open the live training session and move straight into the camera-assisted flow.",
      tag: "Workout",
    },
    {
      href: "/browsePrograms",
      title: "Browse training programs",
      description: "Explore structured plans instead of isolated sessions and build a path through the week.",
      tag: "Programs",
    },
    {
      href: "/progress",
      title: "Review recent momentum",
      description: "Use progress as a real dashboard, not a dead-end page you visit once.",
      tag: "Progress",
    },
  ];

  const sessionFlow = [
    "Pick a workout and start the camera only when you need it.",
    "Use pose detection as guidance, not decoration.",
    "Turn completed sessions into visible progress and next actions.",
  ];

  const weeklyStats = [
    { label: "Workouts ready", value: "06" },
    { label: "Programs active", value: "03" },
    { label: "Focus this week", value: "Mobility" },
  ];

  return (
    <main className="page-shell">
      <div className="section-shell space-y-8">
        <section className="surface-card relative overflow-hidden px-6 py-8 md:px-10 md:py-12">
          <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 bg-[radial-gradient(circle_at_top,rgba(237,104,41,0.18),transparent_48%),radial-gradient(circle_at_70%_70%,rgba(49,132,112,0.20),transparent_44%)] lg:block" />

          <div className="relative grid gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)] lg:items-center">
            <div className="space-y-6">
              <span className="eyebrow">AI-guided training system</span>

              <div className="space-y-4">
                <h1 className="max-w-3xl text-5xl font-semibold tracking-[-0.04em] text-foreground md:text-6xl">
                  Smarter workouts, clearer form, and one place to keep your training moving.
                </h1>

                <p className="max-w-2xl text-base leading-7 text-muted-foreground md:text-lg">
                  AIHM brings together guided sessions, body tracking, and progress so you can train with more structure and less guesswork.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <Link href="/workouts" className="button-primary">
                  Start workout
                </Link>
                <Link href="/browsePrograms" className="button-secondary">
                  Explore programs
                </Link>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-2xl border border-black/10 bg-white/65 px-4 py-4">
                  <div className="text-sm font-medium text-muted-foreground">Session mode</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.03em]">Live</div>
                </div>
                <div className="rounded-2xl border border-black/10 bg-white/65 px-4 py-4">
                  <div className="text-sm font-medium text-muted-foreground">Focus</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.03em]">Strength</div>
                </div>
                <div className="rounded-2xl border border-black/10 bg-white/65 px-4 py-4">
                  <div className="text-sm font-medium text-muted-foreground">Next step</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.03em]">Progress</div>
                </div>
              </div>
            </div>

            <div className="grid-glow relative rounded-[30px] border border-black/10 bg-slate-950 px-5 py-5 text-white shadow-[0_30px_70px_rgba(15,23,42,0.24)]">
              <div className="absolute inset-x-6 top-6 h-px bg-white/10" />

              <div className="space-y-4">
                <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-white/50">Today</div>
                    <div className="mt-1 text-xl font-semibold">Mobility + Core Reset</div>
                  </div>
                  <div className="rounded-full bg-emerald-300/15 px-3 py-1 text-xs font-medium text-emerald-200">
                    Ready
                  </div>
                </div>

                <div className="rounded-[26px] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.10),rgba(255,255,255,0.03))] p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm text-white/60">Camera-assisted session</div>
                      <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">Body alignment in frame</div>
                    </div>
                    <div className="rounded-2xl bg-orange-500/20 px-3 py-2 text-sm font-medium text-orange-100">
                      Tracking
                    </div>
                  </div>

                  <div className="mt-6 grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl bg-white/5 p-4">
                      <div className="text-sm text-white/50">Target joints</div>
                      <div className="mt-2 text-2xl font-semibold">12 active</div>
                    </div>
                    <div className="rounded-2xl bg-white/5 p-4">
                      <div className="text-sm text-white/50">Session state</div>
                      <div className="mt-2 text-2xl font-semibold">Calibrated</div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-white/45">Programs</div>
                    <div className="mt-2 text-lg font-semibold">3 queued</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-white/45">Streak</div>
                    <div className="mt-2 text-lg font-semibold">4 days</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.2em] text-white/45">Mode</div>
                    <div className="mt-2 text-lg font-semibold">Adaptive</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          {highlights.map((item) => (
            <article key={item.title} className="surface-card px-6 py-6">
              <div className="text-sm font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                Core pillar
              </div>
              <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">
                {item.title}
              </h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {item.description}
              </p>
            </article>
          ))}
        </section>

        <section className="surface-card px-6 py-8 md:px-10">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="max-w-2xl">
              <span className="eyebrow">Choose your path</span>
              <h2 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl">
                Start where you need to start today.
              </h2>
            </div>

            <p className="max-w-xl text-sm leading-7 text-muted-foreground md:text-base">
              Jump into a live workout, follow a structured program, or check the momentum you have already built.
            </p>
          </div>

          <div className="mt-8 grid gap-4 lg:grid-cols-3">
            {actions.map((action) => (
              <Link
                key={action.href}
                href={action.href}
                className="group rounded-[26px] border border-black/10 bg-white/72 px-6 py-6 transition-transform duration-150 hover:-translate-y-1"
              >
                <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                  {action.tag}
                </div>
                <h3 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">
                  {action.title}
                </h3>
                <p className="mt-3 text-sm leading-7 text-muted-foreground">
                  {action.description}
                </p>
                <div className="mt-6 text-sm font-semibold text-primary transition-transform duration-150 group-hover:translate-x-1">
                  Open section
                </div>
              </Link>
            ))}
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <article className="surface-card px-6 py-8 md:px-8">
            <span className="eyebrow">Built for consistency</span>
            <h2 className="mt-4 text-3xl font-semibold tracking-[-0.04em] text-foreground">
              AIHM is strongest when training, feedback, and follow-through live in the same loop.
            </h2>
            <p className="mt-4 text-sm leading-7 text-muted-foreground md:text-base">
              Use the app to move from session to session with context. Start a workout, let the camera help when needed, and keep progress visible enough that the next decision is easy.
            </p>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              {weeklyStats.map((stat) => (
                <div key={stat.label} className="rounded-2xl border border-black/10 bg-white/65 px-4 py-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                    {stat.label}
                  </div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-foreground">
                    {stat.value}
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="surface-card px-6 py-8 md:px-8">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Session flow
            </div>
            <div className="mt-6 space-y-4">
              {sessionFlow.map((step, index) => (
                <div key={step} className="flex gap-4 rounded-2xl border border-black/10 bg-white/65 px-4 py-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                    0{index + 1}
                  </div>
                  <p className="text-sm leading-7 text-muted-foreground md:text-base">{step}</p>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="surface-card overflow-hidden px-6 py-8 md:px-10 md:py-10">
          <div className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-center">
            <div className="space-y-4">
              <span className="eyebrow">Ready to train</span>
              <h2 className="max-w-2xl text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl">
                Open a session, get into position, and let AIHM guide the next rep.
              </h2>
              <p className="max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">
                The homepage should make the next action obvious. If today is a training day, start the workout. If you are planning ahead, browse programs. If you need a reset, check progress and continue from there.
              </p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col">
              <Link href="/workouts" className="button-primary">
                Launch workout
              </Link>
              <Link href="/progress" className="button-secondary">
                View progress
              </Link>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
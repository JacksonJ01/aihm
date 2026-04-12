import Link from "next/link";
import {
  BellRing,
  Compass,
  Gauge,
  Layers3,
  MessageSquareMore,
  PlayCircle,
  ShieldCheck,
  UserRound,
  Users2,
} from "lucide-react";

import {
  AppPage,
  InlineLink,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";

const overviewStats = [
  {
    label: "Workout flow",
    value: "Live",
    detail: "Guided sessions, camera-assisted tracking, and quick setup live together in one place.",
    icon: PlayCircle,
  },
  {
    label: "Programs",
    value: "Structured",
    detail: "Browse plans, keep active cycles visible, and carry weekly targets into the next session.",
    icon: Layers3,
  },
  {
    label: "Progress",
    value: "Readable",
    detail: "Recent scores, workload, and consistency stay close enough to actually guide your next choice.",
    icon: Gauge,
  },
];

const trainingCards = [
  {
    href: "/workouts",
    eyebrow: "Workout studio",
    title: "Start a guided session",
    description:
      "Warm up the camera only when needed, keep the session controls in one place, and leave with a clear latest result.",
    points: ["Live camera-assisted flow", "Recent session recap", "Ready-to-train setup guidance"],
  },
  {
    href: "/browsePrograms",
    eyebrow: "Program library",
    title: "Compare plans before you commit",
    description:
      "Browse structured training paths by focus, duration, and difficulty instead of guessing your next block.",
    points: ["Strength, mobility, and conditioning", "Featured plans with strong defaults", "Weekly cadence at a glance"],
  },
  {
    href: "/programs",
    eyebrow: "Current programs",
    title: "Keep active plans in motion",
    description:
      "Track what is active, what is next, and whether the week is still on target without digging through multiple screens.",
    points: ["Progress per plan", "Weekly completion view", "Next-session visibility"],
  },
  {
    href: "/progress",
    eyebrow: "Progress dashboard",
    title: "See whether training is working",
    description:
      "Recent quality, workload, and streaks are shaped into a dashboard that tells you what is improving and what is drifting.",
    points: ["Recent score trend", "Workload summary", "Session highlights"],
  },
];

const networkCards = [
  {
    href: "/community",
    eyebrow: "Community hub",
    title: "Stay close to challenges and discussion",
    description:
      "Short accountability blocks and focused conversations keep the broader training community useful instead of noisy.",
    points: ["Current challenges", "Pinned discussions", "Participation snapshots"],
    icon: MessageSquareMore,
  },
  {
    href: "/friends",
    eyebrow: "Friends",
    title: "Keep accountability personal",
    description:
      "Accepted connections, pending invites, and shared streaks stay visible so the social side of training does real work.",
    points: ["Active circle overview", "Pending follow-ups", "Shared streak visibility"],
    icon: Users2,
  },
  {
    href: "/notifications",
    eyebrow: "Notifications",
    title: "Keep alerts tied to action",
    description:
      "Workout reminders, friend activity, and program updates stay close to the page where each one matters.",
    points: ["Unread inbox", "Activity summary", "Direct next steps"],
    icon: BellRing,
  },
  {
    href: "/profile",
    eyebrow: "Profile",
    title: "Shape the app around your training",
    description:
      "Goals, preferences, camera defaults, and account details stay together so the rest of the experience can adapt around you.",
    points: ["Training goal and level", "Camera and audio preferences", "Account details in one place"],
    icon: UserRound,
  },
];

const flow = [
  "Use the home page as the broad overview of how workouts, programs, progress, and accountability fit together.",
  "Sign in to move from the overview into your own sessions, plans, alerts, and profile details.",
  "Treat each routed page as your personal working view rather than a public preview of the product.",
];

export default function Home() {
  return (
    <AppPage>
      <section className="surface-card relative overflow-hidden px-6 py-8 md:px-10 md:py-12">
        <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 bg-[radial-gradient(circle_at_top,rgba(237,104,41,0.18),transparent_48%),radial-gradient(circle_at_72%_68%,rgba(49,132,112,0.18),transparent_42%)] lg:block" />

        <div className="relative grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] lg:items-center">
          <div className="space-y-6">
            <span className="eyebrow">AIHM overview</span>

            <div className="space-y-4">
              <h1 className="max-w-3xl text-5xl font-semibold tracking-[-0.04em] text-foreground md:text-6xl">
                One homepage for the full system, with the deeper pages reserved for your own training data.
              </h1>

              <p className="max-w-2xl text-base leading-7 text-muted-foreground md:text-lg">
                AIHM now uses the homepage as the public overview of workouts, programs, progress, community, and account tools. Once you sign in, the routed pages become your personalized working views.
              </p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <Link href="/auth/login" className="button-primary">
                Sign in
              </Link>
              <Link href="/workouts" className="button-secondary">
                Open the app
              </Link>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {overviewStats.map((stat) => (
                <StatCard
                  key={stat.label}
                  label={stat.label}
                  value={stat.value}
                  detail={stat.detail}
                  icon={stat.icon}
                />
              ))}
            </div>
          </div>

          <div className="grid gap-4">
            <div className="grid-glow rounded-[30px] border border-black/10 bg-slate-950 px-5 py-5 text-white shadow-[0_30px_70px_rgba(15,23,42,0.24)]">
              <div className="flex items-start gap-3">
                <div className="rounded-full bg-white/10 p-2">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">How it works</div>
                  <div className="mt-3 text-2xl font-semibold tracking-[-0.04em]">Overview first, personal data after sign-in.</div>
                </div>
              </div>

              <div className="mt-6 space-y-3">
                {flow.map((step, index) => (
                  <div key={step} className="flex gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm font-semibold text-white">
                      0{index + 1}
                    </div>
                    <p className="text-sm leading-6 text-white/80">{step}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[28px] border border-black/10 bg-white/75 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Sections included here</div>
              <div className="mt-4 flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Workouts</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Programs</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Progress</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Community</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Friends</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Notifications</span>
                <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">Profile</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <SectionCard
        eyebrow="Training views"
        title="The core training pages, summarized on one screen"
        description="These cards mirror the main training routes so the homepage shows the product clearly before a user moves into their own account data."
      >
        <div className="grid gap-4 xl:grid-cols-2">
          {trainingCards.map((card) => (
            <article key={card.href} className="rounded-[26px] border border-black/10 bg-white/72 px-6 py-6">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                {card.eyebrow}
              </div>
              <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{card.title}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{card.description}</p>
              <div className="mt-5 flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {card.points.map((point) => (
                  <span key={point} className="rounded-full border border-black/10 bg-background/70 px-3 py-1">
                    {point}
                  </span>
                ))}
              </div>
              <div className="mt-6">
                <InlineLink href={card.href}>Open {card.eyebrow.toLowerCase()}</InlineLink>
              </div>
            </article>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        eyebrow="Community and account"
        title="The rest of the app stays visible from the homepage too"
        description="Social activity, alerts, and profile setup are represented here so the homepage reads like a complete map of the product."
      >
        <div className="grid gap-4 xl:grid-cols-2">
          {networkCards.map((card) => {
            const Icon = card.icon;

            return (
              <article key={card.href} className="rounded-[26px] border border-black/10 bg-white/72 px-6 py-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                    {card.eyebrow}
                  </div>
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{card.title}</h2>
                <p className="mt-3 text-sm leading-7 text-muted-foreground">{card.description}</p>
                <div className="mt-5 grid gap-2">
                  {card.points.map((point) => (
                    <div key={point} className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm leading-6 text-muted-foreground">
                      {point}
                    </div>
                  ))}
                </div>
                <div className="mt-6">
                  <InlineLink href={card.href}>Open {card.eyebrow.toLowerCase()}</InlineLink>
                </div>
              </article>
            );
          })}
        </div>
      </SectionCard>

      <section className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <SectionCard
          eyebrow="Program snapshot"
          title="Default product content belongs on the homepage"
          description="The homepage now acts as the broad overview instead of asking each route to double as a public preview."
        >
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Library</div>
                <Compass className="h-5 w-5 text-primary" />
              </div>
              <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-foreground">Structured plans</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">Strength foundations, mobility resets, and conditioning cycles are all introduced from here.</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Dashboard</div>
              <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-foreground">Recent momentum</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">Workload, form quality, and recent activity are summarized here before the personal dashboard takes over.</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Account</div>
              <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-foreground">Personal after sign-in</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">Once signed in, the dedicated pages switch from overview mode into your own data, settings, and activity.</p>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Next step"
          title="Use the homepage as the map, then go straight into your account view"
          description="The deeper routes are still where the real work happens. The difference is that they now feel like personal destinations instead of public teaser pages."
        >
          <div className="space-y-4">
            <div className="rounded-[24px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Recommended path</div>
              <p className="mt-3 text-sm leading-6 text-white/80">
                Sign in, open the section you actually need, and let that page populate from your own sessions, programs, notifications, friendships, and profile settings.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Link href="/auth/login" className="button-primary">
                Continue to sign in
              </Link>
              <Link href="/profile" className="button-secondary">
                Open profile
              </Link>
            </div>
          </div>
        </SectionCard>
      </section>
    </AppPage>
  );
}
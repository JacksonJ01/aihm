import Link from "next/link";
import { BookOpenText, LifeBuoy, ShieldCheck, Wrench } from "lucide-react";

import { AppPage, PageHero, SectionCard, StatCard } from "@/components/app/page-primitives";

const quickLinks = [
  {
    title: "Getting started",
    description: "Learn the intended flow between programs, workouts, and progress so the app feels coherent from day one.",
    href: "/browsePrograms",
    label: "Open programs",
  },
  {
    title: "Camera setup",
    description: "Use a stable angle, clear floor space, and start the camera only when live pose feedback is actually helpful.",
    href: "/workouts",
    label: "Open workout studio",
  },
  {
    title: "Profile and account",
    description: "Review profile data, training preferences, and account details from the profile area.",
    href: "/profile",
    label: "Open profile",
  },
];

const faqs = [
  {
    question: "When should I use the camera?",
    answer: "Use it when posture, joint position, or tempo feedback changes the quality of the session. Leave it off when you only need structure and timing.",
  },
  {
    question: "Why do programs and workouts both exist?",
    answer: "Programs define the weekly structure. Workouts are the execution layer. Keeping them separate makes planning and training both easier to navigate.",
  },
  {
    question: "Why might some pages show sample content?",
    answer: "The UI is ready for Supabase-backed data, but some sections fall back to structured sample content until the required tables exist and have user data.",
  },
];

export default function HelpPage() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Help and docs"
        title="Keep support close to the workflow instead of hiding it behind generic documentation."
        description="This page gives users a fast way to understand how the product is meant to be used, what to do when something feels off, and where to go next."
        actions={[
          { href: "/profile", label: "Open profile", secondary: true },
          { href: "/workouts", label: "Go to workouts" },
        ]}
        aside={
          <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white shadow-[0_24px_60px_rgba(15,23,42,0.24)]">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Support posture</div>
            <p className="mt-3 text-sm leading-6 text-white/70">
              Good help content shortens time-to-action. It should explain the product clearly enough that users can get back to training fast.
            </p>
          </div>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Guides" value="03" detail="Direct entry points into the sections users most often need help with." icon={BookOpenText} />
        <StatCard label="Troubleshooting" value="Ready" detail="Camera setup, flow clarity, and account guidance are covered." icon={Wrench} />
        <StatCard label="Account safety" value="Protected" detail="Authenticated routes remain behind the Supabase session middleware." icon={ShieldCheck} />
        <StatCard label="Support intent" value="Actionable" detail="This page is designed to hand users back into the app, not strand them in docs." icon={LifeBuoy} />
      </section>

      <SectionCard
        eyebrow="Quick access"
        title="Start from the help topic that matches the job"
        description="The most useful support links are the ones that route users back into the correct page immediately."
      >
        <div className="grid gap-4 lg:grid-cols-3">
          {quickLinks.map((item) => (
            <article key={item.title} className="rounded-[26px] border border-black/10 bg-white/72 px-5 py-5">
              <h2 className="text-2xl font-semibold tracking-[-0.03em] text-foreground">{item.title}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{item.description}</p>
              <div className="mt-5">
                <Link href={item.href} className="button-secondary">
                  {item.label}
                </Link>
              </div>
            </article>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        eyebrow="FAQ"
        title="Answers to the questions this product naturally creates"
        description="These entries keep the support page useful even before a full documentation system exists."
      >
        <div className="space-y-4">
          {faqs.map((item) => (
            <article key={item.question} className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5">
              <h3 className="text-xl font-semibold tracking-[-0.03em] text-foreground">{item.question}</h3>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{item.answer}</p>
            </article>
          ))}
        </div>
      </SectionCard>
    </AppPage>
  );
}

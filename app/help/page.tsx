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
    question: "Why is a section empty?",
    answer: "Some areas stay intentionally clear until you have activity, saved preferences, or account details relevant to that section.",
  },
];

export default function HelpPage() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Help and docs"
        title="Keep support close to the workflow instead of hiding it behind generic documentation."
        description="Find quick answers, setup notes, and direct links into the parts of the app you need most."
        actions={[
          { href: "/profile", label: "Open profile", secondary: true },
          { href: "/workouts", label: "Go to workouts" },
        ]}
        aside={
          <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white shadow-[0_24px_60px_rgba(15,23,42,0.24)]">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Support summary</div>
            <p className="mt-3 text-sm leading-6 text-white/70">
              Help topics, troubleshooting notes, and account links are grouped here for quick access.
            </p>
          </div>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Guides" value="03" detail="Direct links into the core areas people open most often from help." icon={BookOpenText} />
        <StatCard label="Troubleshooting" value="Ready" detail="Camera setup, flow clarity, and account notes are available here." icon={Wrench} />
        <StatCard label="Account safety" value="Protected" detail="Sensitive account areas stay limited to signed-in access." icon={ShieldCheck} />
        <StatCard label="Support intent" value="Actionable" detail="Relevant links stay close to the answers they belong to." icon={LifeBuoy} />
      </section>

      <SectionCard
        eyebrow="Quick access"
        title="Start from the help topic that matches the job"
        description="Open the topic that matches what you need, then jump directly into the right part of the app."
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

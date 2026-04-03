import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, Database, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type HeroAction = {
  href: string;
  label: string;
  secondary?: boolean;
};

type PageHeroProps = {
  eyebrow: string;
  title: string;
  description: string;
  actions?: HeroAction[];
  aside?: ReactNode;
};

type SectionCardProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
};

type StatCardProps = {
  label: string;
  value: string;
  detail?: string;
  icon?: LucideIcon;
};

type DataSourceNoticeProps = {
  source: "live" | "sample";
  tables: string[];
};

export function AppPage({ children }: { children: ReactNode }) {
  return <main className="page-shell"><div className="section-shell space-y-8">{children}</div></main>;
}

export function PageHero({ eyebrow, title, description, actions, aside }: PageHeroProps) {
  return (
    <section className="surface-card relative overflow-hidden px-6 py-8 md:px-10 md:py-10">
      <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-1/2 bg-[radial-gradient(circle_at_top,rgba(237,104,41,0.18),transparent_46%),radial-gradient(circle_at_72%_68%,rgba(49,132,112,0.18),transparent_42%)] lg:block" />
      <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)] lg:items-start">
        <div className="space-y-5">
          <span className="eyebrow">{eyebrow}</span>
          <div className="space-y-4">
            <h1 className="max-w-3xl text-4xl font-semibold tracking-[-0.04em] text-foreground md:text-5xl">
              {title}
            </h1>
            <p className="max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">
              {description}
            </p>
          </div>
          {actions && actions.length > 0 ? (
            <div className="flex flex-col gap-3 sm:flex-row">
              {actions.map((action) => (
                <Link
                  key={action.href}
                  href={action.href}
                  className={action.secondary ? "button-secondary" : "button-primary"}
                >
                  {action.label}
                </Link>
              ))}
            </div>
          ) : null}
        </div>

        {aside ? <div className="grid gap-4">{aside}</div> : null}
      </div>
    </section>
  );
}

export function SectionCard({ eyebrow, title, description, children, className }: SectionCardProps) {
  return (
    <section className={cn("surface-card px-6 py-8 md:px-8", className)}>
      {(eyebrow || description) && (
        <div className="mb-6 space-y-3">
          {eyebrow ? <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">{eyebrow}</div> : null}
          <div>
            <h2 className="text-2xl font-semibold tracking-[-0.03em] text-foreground md:text-3xl">{title}</h2>
            {description ? (
              <p className="mt-3 max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">{description}</p>
            ) : null}
          </div>
        </div>
      )}
      {!eyebrow && !description ? (
        <h2 className="mb-6 text-2xl font-semibold tracking-[-0.03em] text-foreground md:text-3xl">{title}</h2>
      ) : null}
      {children}
    </section>
  );
}

export function StatCard({ label, value, detail, icon: Icon }: StatCardProps) {
  return (
    <article className="rounded-[24px] border border-black/10 bg-white/70 px-5 py-5 shadow-[0_18px_40px_rgba(29,35,43,0.08)]">
      <div className="flex items-start justify-between gap-4">
        <div className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">{label}</div>
        {Icon ? <Icon className="h-5 w-5 text-primary" /> : null}
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-foreground">{value}</div>
      {detail ? <p className="mt-3 text-sm leading-6 text-muted-foreground">{detail}</p> : null}
    </article>
  );
}

export function DataSourceNotice({ source, tables }: DataSourceNoticeProps) {
  return (
    <div className="rounded-[24px] border border-black/10 bg-black px-5 py-5 text-white shadow-[0_18px_50px_rgba(15,23,42,0.24)]">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-white/10 p-2">
          <Database className="h-4 w-4" />
        </div>
        <div className="space-y-2">
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-white/65">Data status</div>
          <p className="text-sm leading-6 text-white/85">
            {source === "live"
              ? "This page is reading from Supabase tables configured for the signed-in user."
              : "This page is ready for Supabase, but it is currently showing structured sample content until the tables are set up or populated."}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            {tables.map((table) => (
              <span key={table} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-white/80">
                {table}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function InlineLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 text-sm font-semibold text-primary transition-transform duration-150 hover:translate-x-1">
      {children}
      <ArrowRight className="h-4 w-4" />
    </Link>
  );
}
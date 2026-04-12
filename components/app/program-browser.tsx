"use client";

import { useMemo, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";

import type { Programs } from "@/lib/site-data";

import { InlineLink } from "@/components/app/page-primitives";

type ProgramBrowserProps = {
  programs: Programs[];
};

export function ProgramBrowser({ programs }: ProgramBrowserProps) {
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState("All");
  const [difficulty, setDifficulty] = useState("All");
  const [sortBy, setSortBy] = useState<"featured" | "duration" | "sessions">("featured");

  const focusOptions = useMemo(
    () => ["All", ...Array.from(new Set(programs.map((program) => program.focus_area)))],
    [programs],
  );

  const difficultyOptions = useMemo(
    () => ["All", ...Array.from(new Set(programs.map((program) => program.difficulty)))],
    [programs],
  );

  const filteredPrograms = useMemo(() => {
    const lowered = query.trim().toLowerCase();
    const nextPrograms = programs.filter((program) => {
      const matchesQuery =
        lowered.length === 0 ||
        program.title.toLowerCase().includes(lowered) ||
        program.summary.toLowerCase().includes(lowered) ||
        program.coach_note.toLowerCase().includes(lowered);
      const matchesFocus = focus === "All" || program.focus_area === focus;
      const matchesDifficulty = difficulty === "All" || program.difficulty === difficulty;

      return matchesQuery && matchesFocus && matchesDifficulty;
    });

    return nextPrograms.sort((left, right) => {
      if (sortBy === "duration") {
        return left.duration_weeks - right.duration_weeks;
      }

      if (sortBy === "sessions") {
        return right.sessions_per_week - left.sessions_per_week;
      }

      return Number(right.featured) - Number(left.featured) || left.title.localeCompare(right.title);
    });
  }, [difficulty, focus, programs, query, sortBy]);

  return (
    <div className="space-y-6">
      <div className="rounded-[28px] border border-black/10 bg-white/70 px-5 py-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              <SlidersHorizontal className="h-4 w-4" />
              Explore programs
            </div>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Filter the library by focus, difficulty, and training demand so the page helps users decide instead of just scroll.
            </p>
          </div>
          <div className="rounded-full border border-black/10 bg-background/70 px-4 py-2 text-sm font-medium text-foreground">
            {filteredPrograms.length} results
          </div>
        </div>

        <div className="mt-5 grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))]">
          <label className="flex items-center gap-3 rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by title, summary, or coach note"
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          <select value={focus} onChange={(event) => setFocus(event.target.value)} className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none">
            {focusOptions.map((option) => (
              <option key={option} value={option}>{option === "All" ? "All focus areas" : option}</option>
            ))}
          </select>

          <select value={difficulty} onChange={(event) => setDifficulty(event.target.value)} className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none">
            {difficultyOptions.map((option) => (
              <option key={option} value={option}>{option === "All" ? "All levels" : option}</option>
            ))}
          </select>

          <select value={sortBy} onChange={(event) => setSortBy(event.target.value as "featured" | "duration" | "sessions")} className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none">
            <option value="featured">Sort: Featured first</option>
            <option value="duration">Sort: Shortest cycle</option>
            <option value="sessions">Sort: Weekly demand</option>
          </select>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {filteredPrograms.length ? (
          filteredPrograms.map((program) => (
            <article key={program.id} className="group rounded-[28px] border border-black/10 bg-white/72 px-6 py-6 transition-transform duration-150 hover:-translate-y-1">
              <div className="flex items-center justify-between gap-3">
                <div className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-accent-foreground">
                  {program.focus_area}
                </div>
                {program.featured ? (
                  <div className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    Featured
                  </div>
                ) : null}
              </div>
              <h2 className="mt-5 text-2xl font-semibold tracking-[-0.03em] text-foreground">{program.title}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{program.summary}</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                <div className="rounded-2xl border border-black/10 bg-background/65 px-4 py-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Difficulty</div>
                  <div className="mt-2 text-sm font-semibold text-foreground">{program.difficulty}</div>
                </div>
                <div className="rounded-2xl border border-black/10 bg-background/65 px-4 py-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Duration</div>
                  <div className="mt-2 text-sm font-semibold text-foreground">{program.duration_weeks} weeks</div>
                </div>
                <div className="rounded-2xl border border-black/10 bg-background/65 px-4 py-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Sessions</div>
                  <div className="mt-2 text-sm font-semibold text-foreground">{program.sessions_per_week} / week</div>
                </div>
              </div>
              <p className="mt-5 rounded-2xl border border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                {program.coach_note}
              </p>
              <div className="mt-5">
                <InlineLink href="/programs">Move this into your active plan list</InlineLink>
              </div>
            </article>
          ))
        ) : (
          <div className="xl:col-span-3 rounded-[28px] border border-dashed border-black/10 bg-background/60 px-6 py-8 text-sm leading-7 text-muted-foreground">
            No programs match the current filters. Broaden the search or switch focus areas to explore more options.
          </div>
        )}
      </div>
    </div>
  );
}
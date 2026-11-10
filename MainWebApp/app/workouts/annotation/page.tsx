import type { Metadata } from "next";
import { FileJson2, Film, ShieldCheck } from "lucide-react";

import { AppPage, PageHero, StatCard } from "@/components/app/page-primitives";

import AnnotationStudio from "./annotation-studio";

export const metadata: Metadata = {
  title: "Workout Annotation Studio · AIHM",
  description: "Frame-accurate workout annotation inside the AIHM web app.",
};

export default function WorkoutAnnotationPage() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Workout annotation"
        title="Turn workout footage into structured training data."
        description="Load a video locally, mark activity, sets, repetitions, phases, and form intervals, then export the same portable annotation JSON used by the mobile workflow."
        actions={[{ href: "/workouts", label: "Back to workout studio", secondary: true }]}
        aside={
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            <StatCard label="Video privacy" value="Local" detail="Video bytes remain in this browser." icon={ShieldCheck} />
            <StatCard label="Annotation format" value="JSON" detail="Portable AIHuMo annotation sessions." icon={FileJson2} />
            <StatCard label="Navigation" value="Frame-level" detail="Keyboard and jump controls stay precise." icon={Film} />
          </div>
        }
      />
      <AnnotationStudio />
    </AppPage>
  );
}

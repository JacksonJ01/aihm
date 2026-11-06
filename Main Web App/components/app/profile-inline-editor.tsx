"use client";

import { useActionState, useEffect, useState, type ReactNode } from "react";

import { updateProfileFieldAction } from "@/app/profile/actions";
import { initialAuthActionState } from "@/lib/auth-form";
import { SectionCard } from "@/components/app/page-primitives";
import type { UserProfiles } from "@/lib/site-data";
import { cn } from "@/lib/utils";

type EditableField =
  | "userName"
  | "displayName"
  | "primaryGoal"
  | "weeklyGoal"
  | "focus"
  | "expLevel"
  | "city"
  | "bio"
  | "email";

type ProfileInlineEditorProps = {
  profile: UserProfiles;
};

function fieldInputClassName(editing: boolean) {
  return cn(
    "w-full rounded-2xl border px-4 py-3 text-sm outline-none transition-colors",
    editing
      ? "border-black/20 bg-background/90 text-foreground shadow-[0_0_0_4px_rgba(237,104,41,0.08)]"
      : "border-dashed border-black/10 bg-white/60 text-muted-foreground",
  );
}

function FieldCard({
  title,
  detail,
  displayValue,
  inputValue,
  field,
  inputType = "text",
  rows,
  className,
}: {
  title: string;
  detail: string;
  displayValue: string;
  inputValue: string;
  field: EditableField;
  inputType?: "text" | "email" | "number" | "textarea";
  rows?: number;
  className?: string;
}) {
  const [state, formAction] = useActionState(updateProfileFieldAction, initialAuthActionState);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (state.status === "success") {
      setIsEditing(false);
    }
  }, [state.status]);

  return (
    <form action={formAction} className={cn("rounded-[24px] border border-black/10 bg-white/72 px-5 py-5", className)}>
      <input type="hidden" name="field" value={field} />
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
        <button
          type={isEditing ? "submit" : "button"}
          onClick={() => {
            if (!isEditing) {
              setIsEditing(true);
            }
          }}
          className="text-xs font-medium normal-case tracking-normal text-muted-foreground transition-colors hover:text-foreground"
        >
          {isEditing ? "Done" : "Edit"}
        </button>
      </div>

      <div className="mt-3 text-sm leading-7 text-muted-foreground">{detail}</div>

      <div className="mt-4">
        {isEditing ? (
          inputType === "textarea" ? (
            <textarea
              name={field}
              defaultValue={inputValue}
              rows={rows ?? 4}
              className={cn(fieldInputClassName(true), "resize-none")}
              autoFocus
            />
          ) : (
            <input
              name={field}
              type={inputType}
              defaultValue={inputValue}
              className={fieldInputClassName(true)}
              autoFocus
            />
          )
        ) : (
          <div className="text-2xl font-semibold tracking-[-0.03em] text-foreground">{displayValue}</div>
        )}
      </div>

      {state.status === "error" ? (
        <div className="mt-3 text-sm leading-6 text-rose-700">{state.message}</div>
      ) : null}
    </form>
  );
}

export function ProfileInlineEditor({ profile }: ProfileInlineEditorProps) {
  return (
    <SectionCard
      eyebrow="Profile"
      title="Your profile"
      description="Tap Edit on any card, change that single field, then Done saves just that update back to userProfiles."
      className="space-y-6"
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-2">
        <FieldCard
          title="Display name"
          displayValue={profile.displayName || "Your profile"}
          inputValue={profile.displayName}
          detail="The name shown throughout the app."
          field="displayName"
        />
        <FieldCard
          title="Weekly goal"
          displayValue={profile.weeklyGoal ? `${profile.weeklyGoal} sessions` : "0 sessions"}
          inputValue={String(profile.weeklyGoal)}
          detail="How much training this profile is trying to hold each week."
          field="weeklyGoal"
          inputType="number"
        />
        <FieldCard
          title="Primary focus"
          displayValue={profile.focus || "General"}
          inputValue={profile.focus}
          detail="The dominant lens currently shaping programs and workouts."
          field="focus"
        />
        <FieldCard
          title="Experience"
          displayValue={profile.expLevel || "Not set"}
          inputValue={profile.expLevel}
          detail="Useful context for how aggressive plans and cues should feel."
          field="expLevel"
        />
        <FieldCard
          title="City"
          displayValue={profile.city || "Add city"}
          inputValue={profile.city}
          detail="Where this profile is based and how local context should read."
          field="city"
        />
        <FieldCard
          title="Username"
          displayValue={profile.userName || "Add username"}
          inputValue={profile.userName}
          detail="The handle used for sign-in and sharing profile identity."
          field="userName"
        />
        <FieldCard
          title="Email"
          displayValue={profile.email || "Add email"}
          inputValue={profile.email}
          detail="The email stored on this profile record."
          field="email"
          inputType="email"
          className="lg:col-span-2"
        />
        <FieldCard
          title="Goal"
          displayValue={profile.primaryGoal || "Add a training goal to tailor recommendations and keep the rest of the app aligned with this account."}
          inputValue={profile.primaryGoal}
          detail="What you want the app to keep centered in workouts and recommendations."
          field="primaryGoal"
          inputType="textarea"
          rows={4}
          className="lg:col-span-2"
        />
        <FieldCard
          title="Bio"
          displayValue={profile.bio || "Tell the app a bit about how you train."}
          inputValue={profile.bio}
          detail="A short note that helps the app keep training decisions personal and grounded."
          field="bio"
          inputType="textarea"
          rows={4}
          className="lg:col-span-2"
        />
      </div>
    </SectionCard>
  );
}
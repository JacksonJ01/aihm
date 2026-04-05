"use server";

import { revalidatePath } from "next/cache";

import { createClient } from "@/lib/supabase/server";

const ALLOWED_FOCUS_AREAS = new Set(["General", "Strength", "Mobility", "Recovery", "Conditioning"]);
const ALLOWED_LEVELS = new Set(["Beginner", "Intermediate", "Advanced"]);
const ALLOWED_PREFERRED_TIMES = new Set(["Early mornings", "Mornings", "Midday", "Afternoons", "Evenings"]);
const ALLOWED_RECOVERY_DAYS = new Set([
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
]);

function sanitizeText(value: FormDataEntryValue | null, fallback: string, maxLength: number) {
  const normalized = String(value ?? fallback).trim();
  return normalized.slice(0, maxLength) || fallback;
}

function parseWeeklyGoal(value: FormDataEntryValue | null) {
  const parsedValue = Number(value ?? 4);

  if (!Number.isInteger(parsedValue) || parsedValue < 1 || parsedValue > 14) {
    throw new Error("Weekly goal must be between 1 and 14 sessions.");
  }

  return parsedValue;
}

function sanitizeAllowedValue(
  value: FormDataEntryValue | null,
  fallback: string,
  allowedValues: Set<string>,
) {
  const normalized = sanitizeText(value, fallback, 40);
  return allowedValues.has(normalized) ? normalized : fallback;
}

export async function updateProfileAction(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims?.sub) {
    throw new Error("You must be signed in to update your profile.");
  }

  const userId = data.claims.sub;
  const profilePayload = {
    user_id: userId,
    display_name: sanitizeText(formData.get("display_name"), "Athlete", 80),
    training_goal: sanitizeText(formData.get("training_goal"), "Build a stronger weekly routine.", 300),
    weekly_goal: parseWeeklyGoal(formData.get("weekly_goal")),
    focus_area: sanitizeAllowedValue(formData.get("focus_area"), "General", ALLOWED_FOCUS_AREAS),
    level: sanitizeAllowedValue(formData.get("level"), "Intermediate", ALLOWED_LEVELS),
    city: sanitizeText(formData.get("city"), "Remote", 80),
    bio: sanitizeText(formData.get("bio"), "", 500),
  };

  const preferencesPayload = {
    user_id: userId,
    camera_enabled: formData.get("camera_enabled") === "on",
    audio_cues: formData.get("audio_cues") === "on",
    preferred_time: sanitizeAllowedValue(
      formData.get("preferred_time"),
      "Evenings",
      ALLOWED_PREFERRED_TIMES,
    ),
    recovery_day: sanitizeAllowedValue(formData.get("recovery_day"), "Sunday", ALLOWED_RECOVERY_DAYS),
  };

  const [{ error: profileError }, { error: preferencesError }] = await Promise.all([
    supabase.from("user_profiles").upsert(profilePayload, { onConflict: "user_id" }),
    supabase.from("training_preferences").upsert(preferencesPayload, { onConflict: "user_id" }),
  ]);

  if (profileError || preferencesError) {
    throw profileError ?? preferencesError;
  }

  revalidatePath("/profile");
}
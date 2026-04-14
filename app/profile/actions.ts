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
  const { data: existingProfile } = await supabase
    .from("userProfiles")
    .select("userName, email")
    .eq("id", userId)
    .maybeSingle();

  const displayName = sanitizeText(formData.get("display_name"), "Athlete", 80);
  const generatedUserName = sanitizeText(formData.get("display_name"), "Athlete", 24)
    .replace(/\s+/g, "_")
    .replace(/[^A-Za-z0-9_]/g, "")
    .toLowerCase();
  const fallbackUserName = `${generatedUserName || "athlete"}_${userId.slice(0, 8)}`;
  const resolvedUserName = (existingProfile?.userName as string | undefined) || fallbackUserName;
  const resolvedEmail = (existingProfile?.email as string | undefined) || data.claims.email;

  if (!resolvedEmail) {
    throw new Error("Unable to resolve profile email for this account.");
  }

  const profilePayload = {
    id: userId,
    userName: resolvedUserName,
    displayName,
    primaryGoal: sanitizeText(formData.get("training_goal"), "Build a stronger weekly routine.", 300),
    weeklyGoal: parseWeeklyGoal(formData.get("weekly_goal")),
    focus: sanitizeAllowedValue(formData.get("focus_area"), "General", ALLOWED_FOCUS_AREAS),
    expLevel: sanitizeAllowedValue(formData.get("level"), "Intermediate", ALLOWED_LEVELS),
    city: sanitizeText(formData.get("city"), "Remote", 80),
    bio: sanitizeText(formData.get("bio"), "", 500),
    email: resolvedEmail,
  };

  const preferencesPayload = {
    userID: userId,
    camEnabled: formData.get("camera_enabled") === "on",
    audioEnabled: formData.get("audio_cues") === "on",
    timePref: sanitizeAllowedValue(
      formData.get("preferred_time"),
      "Evenings",
      ALLOWED_PREFERRED_TIMES,
    ),
    recoveryDay: sanitizeAllowedValue(formData.get("recovery_day"), "Sunday", ALLOWED_RECOVERY_DAYS),
  };

  const [{ error: profileError }, { error: preferencesError }] = await Promise.all([
    supabase.from("userProfiles").upsert(profilePayload, { onConflict: "id" }),
    supabase.from("workoutPref").upsert(preferencesPayload, { onConflict: "userID" }),
  ]);

  if (profileError || preferencesError) {
    throw profileError ?? preferencesError;
  }

  revalidatePath("/profile");
}
"use server";

import { revalidatePath } from "next/cache";

import { isValidEmail, type AuthActionState } from "@/lib/auth-form";
import { createClient } from "@/lib/supabase/server";

const ALLOWED_FOCUS_AREAS = new Set(["General", "Strength", "Mobility", "Recovery", "Conditioning"]);
const ALLOWED_LEVELS = new Set(["Beginner", "Intermediate", "Advanced"]);

type EditableProfileField =
  | "userName"
  | "displayName"
  | "primaryGoal"
  | "weeklyGoal"
  | "focus"
  | "expLevel"
  | "city"
  | "bio"
  | "email";

function sanitizeText(value: FormDataEntryValue | null, fallback: string, maxLength: number) {
  const normalized = String(value ?? fallback).trim();
  return normalized.slice(0, maxLength) || fallback;
}

function parseWeeklyGoal(value: FormDataEntryValue | null) {
  const parsedValue = Number(value ?? 0);

  if (!Number.isInteger(parsedValue) || parsedValue < 0) {
    throw new Error("Weekly goal must be 0 or higher.");
  }

  return parsedValue;
}

function sanitizeUserName(value: FormDataEntryValue | null, fallback: string) {
  const normalized = String(value ?? fallback)
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^A-Za-z0-9_]/g, "");

  return normalized.slice(0, 40) || fallback;
}

function sanitizeAllowedValue(
  value: FormDataEntryValue | null,
  fallback: string,
  allowedValues: Set<string>,
) {
  const normalized = sanitizeText(value, fallback, 40);
  return allowedValues.has(normalized) ? normalized : fallback;
}

function isEditableProfileField(value: string): value is EditableProfileField {
  return [
    "userName",
    "displayName",
    "primaryGoal",
    "weeklyGoal",
    "focus",
    "expLevel",
    "city",
    "bio",
    "email",
  ].includes(value);
}

async function isUserNameTaken(supabase: Awaited<ReturnType<typeof createClient>>, userName: string, userId: string) {
  const { data, error } = await supabase
    .from("userProfiles")
    .select("id")
    .eq("userName", userName)
    .neq("id", userId)
    .limit(1);

  if (error) {
    throw error;
  }

  return (data?.length ?? 0) > 0;
}

async function isEmailTaken(supabase: Awaited<ReturnType<typeof createClient>>, email: string, userId: string) {
  const { data, error } = await supabase
    .from("userProfiles")
    .select("id")
    .eq("email", email)
    .neq("id", userId)
    .limit(1);

  if (error) {
    throw error;
  }

  return (data?.length ?? 0) > 0;
}

type ProfileRow = {
  id: string;
  userName: string;
  displayName: string;
  primaryGoal: string;
  weeklyGoal: number;
  focus: string;
  expLevel: string;
  city: string;
  bio: string;
  email: string;
};

async function getCurrentProfileRow(supabase: Awaited<ReturnType<typeof createClient>>, userId: string) {
  const { data, error } = await supabase
    .from("userProfiles")
    .select("id, userName, displayName, primaryGoal, weeklyGoal, focus, expLevel, city, bio, email")
    .eq("id", userId)
    .maybeSingle();

  if (error) {
    throw error;
  }

  return (data as ProfileRow | null) ?? null;
}

function getProfilePayloadForField(profile: ProfileRow, field: EditableProfileField, formData: FormData) {
  switch (field) {
    case "userName": {
      const userName = sanitizeUserName(formData.get(field), profile.userName);
      return { ...profile, userName };
    }
    case "displayName":
      return { ...profile, displayName: sanitizeText(formData.get(field), profile.displayName, 80) };
    case "primaryGoal":
      return { ...profile, primaryGoal: sanitizeText(formData.get(field), profile.primaryGoal, 300) };
    case "weeklyGoal":
      return { ...profile, weeklyGoal: parseWeeklyGoal(formData.get(field)) };
    case "focus":
      return { ...profile, focus: sanitizeAllowedValue(formData.get(field), profile.focus || "General", ALLOWED_FOCUS_AREAS) };
    case "expLevel":
      return { ...profile, expLevel: sanitizeAllowedValue(formData.get(field), profile.expLevel || "Intermediate", ALLOWED_LEVELS) };
    case "city":
      return { ...profile, city: sanitizeText(formData.get(field), profile.city, 80) };
    case "bio":
      return { ...profile, bio: sanitizeText(formData.get(field), profile.bio, 500) };
    case "email": {
      const email = sanitizeText(formData.get(field), profile.email, 254);
      return { ...profile, email };
    }
  }
}

export async function updateProfileFieldAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims?.sub) {
    return { status: "error", message: "You must be signed in to update your profile." };
  }

  const userId = data.claims.sub;
  const field = String(formData.get("field") ?? "").trim();

  if (!isEditableProfileField(field)) {
    return { status: "error", message: "Choose a valid profile field to update." };
  }

  const currentProfile = await getCurrentProfileRow(supabase, userId);

  if (!currentProfile) {
    return { status: "error", message: "Profile record not found." };
  }

  const nextProfile = getProfilePayloadForField(currentProfile, field, formData);

  if (field === "userName") {
    const taken = await isUserNameTaken(supabase, nextProfile.userName, userId);
    if (taken) {
      return { status: "error", message: `Username "${nextProfile.userName}" is already taken. Try another.` };
    }
  }

  if (field === "email") {
    if (!isValidEmail(nextProfile.email)) {
      return { status: "error", message: "Enter a valid email address." };
    }

    const taken = await isEmailTaken(supabase, nextProfile.email, userId);
    if (taken) {
      return { status: "error", message: `Email "${nextProfile.email}" is already used by another profile.` };
    }
  }

  const { error: profileError } = await supabase
    .from("userProfiles")
    .upsert(nextProfile, { onConflict: "id" });

  if (profileError) {
    return { status: "error", message: profileError.message || "Could not update your profile right now." };
  }

  revalidatePath("/profile");

  return { status: "success", message: `${field} updated.` };
}

export async function updateProfileAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims?.sub) {
    return { status: "error", message: "You must be signed in to update your profile." };
  }

  const userId = data.claims.sub;
  const { data: existingProfile } = await supabase
    .from("userProfiles")
    .select("userName, email")
    .eq("id", userId)
    .maybeSingle();

  const fallbackUserName = existingProfile?.userName || `athlete_${userId.slice(0, 8)}`;
  const resolvedUserName = sanitizeUserName(formData.get("userName"), fallbackUserName);
  const userNameTaken = await isUserNameTaken(supabase, resolvedUserName, userId);

  if (userNameTaken) {
    return { status: "error", message: `Username "${resolvedUserName}" is already taken. Try another.` };
  }

  const resolvedEmail = sanitizeText(formData.get("email"), existingProfile?.email || data.claims.email || "", 254);

  if (!resolvedEmail || !isValidEmail(resolvedEmail)) {
    return { status: "error", message: "Enter a valid email address." };
  }

  const emailTaken = await isEmailTaken(supabase, resolvedEmail, userId);

  if (emailTaken) {
    return { status: "error", message: `Email "${resolvedEmail}" is already used by another profile.` };
  }

  const displayName = sanitizeText(formData.get("displayName"), "Athlete", 80);

  const profilePayload = {
    id: userId,
    userName: resolvedUserName,
    displayName,
    primaryGoal: sanitizeText(formData.get("primaryGoal"), "Build a stronger weekly routine.", 300),
    weeklyGoal: parseWeeklyGoal(formData.get("weeklyGoal")),
    focus: sanitizeAllowedValue(formData.get("focus"), "General", ALLOWED_FOCUS_AREAS),
    expLevel: sanitizeAllowedValue(formData.get("expLevel"), "Intermediate", ALLOWED_LEVELS),
    city: sanitizeText(formData.get("city"), "Remote", 80),
    bio: sanitizeText(formData.get("bio"), "", 500),
    email: resolvedEmail,
  };

  const { error: profileError } = await supabase
    .from("userProfiles")
    .upsert(profilePayload, { onConflict: "id" });

  if (profileError) {
    return { status: "error", message: profileError.message || "Could not update your profile right now." };
  }

  revalidatePath("/profile");

  return { status: "success", message: "Profile updated." };
}
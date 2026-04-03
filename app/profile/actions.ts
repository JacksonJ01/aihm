"use server";

import { revalidatePath } from "next/cache";

import { createClient } from "@/lib/supabase/server";

export async function updateProfileAction(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims?.sub) {
    throw new Error("You must be signed in to update your profile.");
  }

  const userId = data.claims.sub;
  const profilePayload = {
    user_id: userId,
    display_name: String(formData.get("display_name") ?? "").trim(),
    training_goal: String(formData.get("training_goal") ?? "").trim(),
    weekly_goal: Number(formData.get("weekly_goal") ?? 4),
    focus_area: String(formData.get("focus_area") ?? "General").trim(),
    level: String(formData.get("level") ?? "Intermediate").trim(),
    city: String(formData.get("city") ?? "Remote").trim(),
    bio: String(formData.get("bio") ?? "").trim(),
  };

  const preferencesPayload = {
    user_id: userId,
    camera_enabled: formData.get("camera_enabled") === "on",
    audio_cues: formData.get("audio_cues") === "on",
    preferred_time: String(formData.get("preferred_time") ?? "Evenings").trim(),
    recovery_day: String(formData.get("recovery_day") ?? "Sunday").trim(),
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
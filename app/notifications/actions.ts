"use server";

import { revalidatePath } from "next/cache";

import { createClient } from "@/lib/supabase/server";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function getAuthedClient() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims?.sub) {
    throw new Error("You must be signed in to update notifications.");
  }

  return {
    supabase,
    userId: data.claims.sub,
  };
}

export async function markNotificationReadAction(formData: FormData) {
  const { supabase, userId } = await getAuthedClient();
  const notificationId = String(formData.get("notification_id") ?? "").trim();

  if (!notificationId || !UUID_PATTERN.test(notificationId)) {
    return;
  }

  const { error } = await supabase
    .from("notifications")
    .update({ is_read: true })
    .eq("id", notificationId)
    .eq("user_id", userId);

  if (error) {
    throw error;
  }

  revalidatePath("/notifications");
}

export async function markAllNotificationsReadAction() {
  const { supabase, userId } = await getAuthedClient();
  const { error } = await supabase
    .from("notifications")
    .update({ is_read: true })
    .eq("user_id", userId)
    .eq("is_read", false);

  if (error) {
    throw error;
  }

  revalidatePath("/notifications");
}
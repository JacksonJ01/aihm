"use server";

import { revalidatePath } from "next/cache";

import { createClient } from "@/lib/supabase/server";

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

  if (!notificationId) {
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
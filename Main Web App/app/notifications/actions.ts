"use server";

import { revalidatePath } from "next/cache";

import { createClient } from "@/lib/supabase/server";

const INTEGER_ID_PATTERN = /^\d+$/;

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
  const notificationIdRaw = String(formData.get("notification_id") ?? "").trim();

  if (!notificationIdRaw || !INTEGER_ID_PATTERN.test(notificationIdRaw)) {
    return;
  }

  const notificationId = Number(notificationIdRaw);

  if (!Number.isSafeInteger(notificationId) || notificationId <= 0) {
    return;
  }

  const { error } = await supabase
    .from("notifications")
    .update({ isRead: true })
    .eq("id", notificationId)
    .eq("userID", userId);

  if (error) {
    throw error;
  }

  revalidatePath("/notifications");
}

export async function markAllNotificationsReadAction() {
  const { supabase, userId } = await getAuthedClient();
  const { error } = await supabase
    .from("notifications")
    .update({ isRead: true })
    .eq("userID", userId)
    .eq("isRead", false);

  if (error) {
    throw error;
  }

  revalidatePath("/notifications");
}
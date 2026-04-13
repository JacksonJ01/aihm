import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ??
  process.env.NEXT_PUBLIC_aihm_SUPABASE_URL ??
  "";

export const supabasePublishableKey =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_aihm_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
  process.env.NEXT_PUBLIC_aihm_SUPABASE_ANON_KEY ??
  "";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getSafeAppPath(pathname: string | null | undefined) {
  if (!pathname) {
    return null;
  }

  if (!pathname.startsWith("/") || pathname.startsWith("//")) {
    return null;
  }

  return pathname;
}

export function getMissingSupabaseEnvVars() {
  const missing: string[] = [];

  if (!supabaseUrl) {
    missing.push("NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_aihm_SUPABASE_URL");
  }

  if (!supabasePublishableKey) {
    missing.push(
      "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY or NEXT_PUBLIC_aihm_SUPABASE_PUBLISHABLE_KEY",
    );
  }

  return missing;
}

export const hasEnvVars = getMissingSupabaseEnvVars().length === 0;

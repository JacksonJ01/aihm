import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

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

// This check can be removed, it is just for tutorial purposes
export const hasEnvVars =
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

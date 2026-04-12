import { createClient } from "@/lib/supabase/server";
import { type EmailOtpType } from "@supabase/supabase-js";
import { redirect } from "next/navigation";
import { type NextRequest } from "next/server";

function getSafeRedirectTarget(next: string | null) {
  if (!next) {
    return "/";
  }

  if (!next.startsWith("/") || next.startsWith("//")) {
    return "/";
  }

  return next;
}

function sanitizeUserName(value: unknown, fallback: string) {
  const normalized = String(value ?? fallback).trim().slice(0, 40).replace(/\s+/g, "_");

  if (/^[A-Za-z0-9_]+$/.test(normalized)) {
    return normalized;
  }

  return fallback;
}

function sanitizeDisplayName(value: unknown, fallback: string) {
  const normalized = String(value ?? fallback).trim().slice(0, 60);
  return normalized || fallback;
}

async function bootstrapConfirmedUser(supabase: Awaited<ReturnType<typeof createClient>>) {
  const { data: userData } = await supabase.auth.getUser();
  const user = userData.user;

  if (!user?.id || !user.email) {
    return;
  }

  const fallbackUserName = user.email.split("@")[0] || "Athlete";
  const metadata = user.user_metadata && typeof user.user_metadata === "object"
    ? user.user_metadata as Record<string, unknown>
    : {};

  const userName = sanitizeUserName(metadata.userName, fallbackUserName);
  const displayName = sanitizeDisplayName(metadata.displayName, fallbackUserName);

  const { data: existingProfile, error: existingProfileError } = await supabase
    .from("userProfiles")
    .select("id, userName")
    .eq("id", user.id)
    .limit(1)
    .maybeSingle();

  if (existingProfileError) {
    console.error("[auth-confirm] Failed checking existing user profile", {
      email: user.email,
      error: existingProfileError,
    });
    throw existingProfileError;
  }

  if (existingProfile) {
    return;
  }

  const { error: profileError } = await supabase.from("userProfiles").insert(
    {
      id: user.id,
      userName,
      displayName,
      primaryGoal: "",
      expLevel: "Beginner",
      weeklyGoal: 0,
      city: "",
      bio: "",
      focus: "General",
      email: user.email,
    },
  );

  if (profileError) {
    console.error("[auth-confirm] Failed creating user profile", {
      email: user.email,
      userName,
      error: profileError,
    });
    throw profileError;
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const next = getSafeRedirectTarget(searchParams.get("next"));

  const supabase = await createClient();

  // Newer Supabase flows can return a PKCE code instead of token_hash/type.
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);

    if (!error) {
      try {
        await bootstrapConfirmedUser(supabase);
      } catch (profileError) {
        console.error("[auth-confirm] profile bootstrap failed after code exchange", {
          error: profileError,
        });
      }
      redirect(next);
    }

    console.error("[auth-confirm] exchangeCodeForSession failed", { error });

    redirect("/auth/error?code=invalid-link");
  }

  if (token_hash && type) {
    const { error } = await supabase.auth.verifyOtp({
      type,
      token_hash,
    });
    if (!error) {
      try {
        await bootstrapConfirmedUser(supabase);
      } catch (profileError) {
        console.error("[auth-confirm] profile bootstrap failed after verifyOtp", {
          error: profileError,
        });
      }
      redirect(next);
    } else {
      console.error("[auth-confirm] verifyOtp failed", { error, type });
      redirect("/auth/error?code=invalid-link");
    }
  }

  redirect("/auth/error?code=invalid-request");
}

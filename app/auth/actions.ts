"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import {
  type AuthActionState,
  getAuthActionMessage,
  isValidEmail,
  normalizeEmail,
  validatePassword,
} from "@/lib/auth-form";
import { consumeRateLimit } from "@/lib/rate-limit";
import { createClient } from "@/lib/supabase/server";
import { verifyTurnstileToken } from "@/lib/turnstile";
import { getSafeAppPath, hasEnvVars } from "@/lib/utils";

const DEFAULT_ERROR_MESSAGE = "Authentication is temporarily unavailable.";

type BootstrapClient = Awaited<ReturnType<typeof createClient>>;

type SignupProfileSeed = {
  userName: string;
  displayName: string;
};

function getRequestIp(headerStore: Headers) {
  return (
    headerStore.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    headerStore.get("x-real-ip") ||
    "unknown"
  );
}

function getBaseUrl(headerStore: Headers) {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_SITE_URL ?? process.env.SITE_URL;

  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }

  const host = headerStore.get("x-forwarded-host") ?? headerStore.get("host");
  const protocol = headerStore.get("x-forwarded-proto") ?? (process.env.NODE_ENV === "production" ? "https" : "http");

  if (!host) {
    throw new Error("Application URL is not configured.");
  }

  return `${protocol}://${host}`;
}

function getRateLimitMessage(retryAfterMs: number) {
  const retryAfterSeconds = Math.max(Math.ceil(retryAfterMs / 1000), 1);
  return `Too many attempts. Try again in ${retryAfterSeconds} seconds.`;
}

function normalizePostAuthPath(pathname: string | null | undefined) {
  const safePath = getSafeAppPath(pathname);

  if (!safePath || safePath === "/protected") {
    return "/";
  }

  return safePath;
}

function getUpdatePasswordErrorMessage(error: unknown) {
  if (
    error &&
    typeof error === "object" &&
    "message" in error &&
    typeof error.message === "string" &&
    error.message.toLowerCase().includes("auth session missing")
  ) {
    return "Your password reset session expired or is invalid. Open the latest reset email and try again.";
  }

  return getAuthActionMessage("update-password");
}

async function enforceTurnstile(formData: FormData, headerStore: Headers) {
  const verification = await verifyTurnstileToken(
    String(formData.get("cf-turnstile-response") ?? "").trim(),
    getRequestIp(headerStore),
  );

  if (!verification.success) {
    return {
      status: "error",
      message: verification.message ?? DEFAULT_ERROR_MESSAGE,
    } satisfies AuthActionState;
  }

  return null;
}

function ensureAuthConfigured() {
  if (!hasEnvVars) {
    return {
      status: "error",
      message: DEFAULT_ERROR_MESSAGE,
    } satisfies AuthActionState;
  }

  return null;
}

function sanitizeText(value: FormDataEntryValue | string | null | undefined, fallback: string, maxLength: number) {
  const normalized = String(value ?? fallback).trim();
  return normalized.slice(0, maxLength) || fallback;
}

function sanitizeUserName(value: FormDataEntryValue | string | null | undefined, fallback: string) {
  const normalized = sanitizeText(value, fallback, 40).replace(/\s+/g, "_");

  if (!/^[A-Za-z0-9_]+$/.test(normalized)) {
    throw new Error("Username can contain only letters, numbers, and underscores.");
  }

  return normalized;
}

function sanitizeDisplayName(value: FormDataEntryValue | string | null | undefined, fallback: string) {
  return sanitizeText(value, fallback, 60);
}

async function isUserNameTaken(supabase: BootstrapClient, userName: string): Promise<boolean> {
  const { data } = await supabase.from("userProfiles").select("userName").eq("userName", userName).limit(1);
  return (data?.length ?? 0) > 0;
}

function getSignupProfileSeedFromForm(formData: FormData, email: string): SignupProfileSeed {
  return {
    userName: sanitizeUserName(formData.get("user_name"), email.split("@")[0] || "Athlete"),
    displayName: sanitizeDisplayName(formData.get("display_name"), email.split("@")[0] || "Athlete"),
  };
}

function getSignupProfileSeedFromMetadata(metadata: unknown, email: string): SignupProfileSeed {
  const source = metadata && typeof metadata === "object" ? metadata as Record<string, unknown> : {};

  return {
    userName: sanitizeUserName(source.userName as string | undefined, email.split("@")[0] || "Athlete"),
    displayName: sanitizeDisplayName(source.displayName as string | undefined, email.split("@")[0] || "Athlete"),
  };
}

async function bootstrapUserData(
  supabase: BootstrapClient,
  userId: string,
  email: string,
  profileSeed: SignupProfileSeed,
): Promise<void> {
  const profilePayload = {
    id: userId,
    userName: profileSeed.userName,
    displayName: profileSeed.displayName,
    primaryGoal: "",
    expLevel: "Beginner",
    weeklyGoal: 0,
    city: "",
    bio: "",
    focus: "General",
    email,
  };

  const { data: existingProfile, error: existingProfileError } = await supabase
    .from("userProfiles")
    .select("id, userName")
    .eq("id", userId)
    .limit(1)
    .maybeSingle();

  if (existingProfileError) {
    console.error("[auth] Failed checking existing user profile", {
      email,
      error: existingProfileError,
    });
    throw existingProfileError;
  }

  if (existingProfile) {
    return;
  }

  const { error: profileError } = await supabase
    .from("userProfiles")
    .insert(profilePayload);

  if (profileError) {
    console.error("[auth] Failed creating user profile", {
      email,
      userName: profileSeed.userName,
      error: profileError,
    });
    throw profileError;
  }
}

export async function loginAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const headerStore = await headers();
  const nextPath = normalizePostAuthPath(String(formData.get("next") ?? "").trim());
  const identifier = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  if (!identifier) {
    return { status: "error", message: "Enter your email or username." };
  }

  if (!password) {
    return { status: "error", message: "Enter your password." };
  }

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
  }

  const supabase = await createClient();

  // Detect whether identifier is username or email, resolve to email for auth.
  let email: string;
  if (isValidEmail(identifier)) {
    email = normalizeEmail(identifier);
  } else {
    // Treat as username; look up email from userProfiles.
    const { data } = await supabase.from("userProfiles").select("email").eq("userName", identifier).limit(1).maybeSingle();
    if (!data?.email) {
      return { status: "error", message: getAuthActionMessage("login") };
    }
    email = data.email;
  }

  const rateLimit = consumeRateLimit({
    key: `login:${getRequestIp(headerStore)}:${email}`,
    limit: 5,
    windowMs: 60_000,
  });

  if (!rateLimit.ok) {
    return { status: "error", message: getRateLimitMessage(rateLimit.retryAfterMs) };
  }

  const turnstileError = await enforceTurnstile(formData, headerStore);

  if (turnstileError) {
    return turnstileError;
  }

  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    console.error("[auth] signInWithPassword failed", { email, error });
    return { status: "error", message: getAuthActionMessage("login") };
  }

  if (data.user?.id) {
    try {
      const profileSeed = getSignupProfileSeedFromMetadata(data.user.user_metadata, data.user.email ?? email);
      await bootstrapUserData(supabase, data.user.id, data.user.email ?? email, profileSeed);
    } catch (error) {
      console.error("[auth] login bootstrap failed", {
        userId: data.user.id,
        email: data.user.email ?? email,
        error,
      });
    }
  }

  redirect(nextPath);
}

export async function signUpAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const headerStore = await headers();
  const email = normalizeEmail(String(formData.get("email") ?? ""));
  const password = String(formData.get("password") ?? "");
  const repeatPassword = String(formData.get("repeat_password") ?? "");

  if (!isValidEmail(email)) {
    return { status: "error", message: "Enter a valid email address." };
  }

  const passwordValidationMessage = validatePassword(password);

  if (passwordValidationMessage) {
    return { status: "error", message: passwordValidationMessage };
  }

  if (password !== repeatPassword) {
    return { status: "error", message: "Passwords do not match." };
  }

  let profileSeed: SignupProfileSeed;

  try {
    profileSeed = getSignupProfileSeedFromForm(formData, email);
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Invalid signup details.",
    };
  }

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
  }

  const supabase = await createClient();

  // Validate username uniqueness before proceeding (checked against existing userProfiles).
  const userNameTaken = await isUserNameTaken(supabase, profileSeed.userName);
  if (userNameTaken) {
    return {
      status: "error",
      message: `Username "${profileSeed.userName}" is already taken. Try another.`,
    };
  }

  const rateLimit = consumeRateLimit({
    key: `signup:${getRequestIp(headerStore)}:${email}`,
    limit: 3,
    windowMs: 10 * 60_000,
  });

  if (!rateLimit.ok) {
    return { status: "error", message: getRateLimitMessage(rateLimit.retryAfterMs) };
  }

  const turnstileError = await enforceTurnstile(formData, headerStore);

  if (turnstileError) {
    return turnstileError;
  }

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo: new URL("/auth/confirm?next=/", getBaseUrl(headerStore)).toString(),
      data: profileSeed,
    },
  });

  if (error) {
    console.error("[auth] signUp failed", {
      email,
      userName: profileSeed.userName,
      error,
    });
    return { status: "error", message: getAuthActionMessage("signup") };
  }

  if (data.session && data.user?.id) {
    try {
      await bootstrapUserData(supabase, data.user.id, data.user.email ?? email, profileSeed);
    } catch (error) {
      console.error("[auth] signup bootstrap failed", {
        userId: data.user.id,
        email: data.user.email ?? email,
        userName: profileSeed.userName,
        error,
      });
    }
  }

  redirect("/auth/sign-up-success");
}

export async function forgotPasswordAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const headerStore = await headers();
  const email = normalizeEmail(String(formData.get("email") ?? ""));

  if (!isValidEmail(email)) {
    return { status: "error", message: "Enter a valid email address." };
  }

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
  }

  const rateLimit = consumeRateLimit({
    key: `forgot-password:${getRequestIp(headerStore)}:${email}`,
    limit: 3,
    windowMs: 15 * 60_000,
  });

  if (!rateLimit.ok) {
    return { status: "error", message: getRateLimitMessage(rateLimit.retryAfterMs) };
  }

  const turnstileError = await enforceTurnstile(formData, headerStore);

  if (turnstileError) {
    return turnstileError;
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: new URL("/auth/confirm?next=/auth/update-password", getBaseUrl(headerStore)).toString(),
  });

  if (error) {
    console.error("[auth] resetPasswordForEmail failed", { email, error });
    return { status: "error", message: getAuthActionMessage("forgot-password") };
  }

  return {
    status: "success",
    message:
      "If an account exists for that email address, a reset link has been sent.",
  };
}

export async function updatePasswordAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const headerStore = await headers();
  const password = String(formData.get("password") ?? "");
  const repeatPassword = String(formData.get("repeat_password") ?? "");
  const passwordValidationMessage = validatePassword(password);

  if (passwordValidationMessage) {
    return { status: "error", message: passwordValidationMessage };
  }

  if (password !== repeatPassword) {
    return { status: "error", message: "Passwords do not match." };
  }

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
  }

  const rateLimit = consumeRateLimit({
    key: `update-password:${getRequestIp(headerStore)}`,
    limit: 5,
    windowMs: 10 * 60_000,
  });

  if (!rateLimit.ok) {
    return { status: "error", message: getRateLimitMessage(rateLimit.retryAfterMs) };
  }

  const turnstileError = await enforceTurnstile(formData, headerStore);

  if (turnstileError) {
    return turnstileError;
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.updateUser({ password });

  if (error) {
    console.error("[auth] updateUser password failed", { error });
    return { status: "error", message: getUpdatePasswordErrorMessage(error) };
  }

  redirect("/protected");
}

export async function logoutAction() {
  if (hasEnvVars) {
    const supabase = await createClient();
    await supabase.auth.signOut();
  }

  redirect("/auth/login");
}
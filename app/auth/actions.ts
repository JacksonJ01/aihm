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
import { hasEnvVars } from "@/lib/utils";

const DEFAULT_ERROR_MESSAGE = "Authentication is temporarily unavailable.";

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

export async function loginAction(
  _previousState: AuthActionState,
  formData: FormData,
): Promise<AuthActionState> {
  const headerStore = await headers();
  const email = normalizeEmail(String(formData.get("email") ?? ""));
  const password = String(formData.get("password") ?? "");

  if (!isValidEmail(email)) {
    return { status: "error", message: "Enter a valid email address." };
  }

  if (!password) {
    return { status: "error", message: "Enter your password." };
  }

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
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

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    return { status: "error", message: getAuthActionMessage("login") };
  }

  redirect("/protected");
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

  const authConfigError = ensureAuthConfigured();

  if (authConfigError) {
    return authConfigError;
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

  const supabase = await createClient();
  const { error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      emailRedirectTo: new URL("/protected", getBaseUrl(headerStore)).toString(),
    },
  });

  if (error) {
    return { status: "error", message: getAuthActionMessage("signup") };
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
  await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: new URL("/auth/update-password", getBaseUrl(headerStore)).toString(),
  });

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
    return { status: "error", message: getAuthActionMessage("update-password") };
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
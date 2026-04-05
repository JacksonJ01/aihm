const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export type AuthActionState = {
  status: "idle" | "error" | "success";
  message?: string;
};

export const initialAuthActionState: AuthActionState = {
  status: "idle",
};

type CooldownKey = "login" | "signup" | "forgot-password" | "update-password";

const ATTEMPT_WINDOWS: Record<CooldownKey, number> = {
  login: 3_000,
  signup: 10_000,
  "forgot-password": 15_000,
  "update-password": 5_000,
};

export function normalizeEmail(value: string) {
  return value.trim().toLowerCase();
}

export function isValidEmail(value: string) {
  return EMAIL_PATTERN.test(normalizeEmail(value));
}

export function validatePassword(value: string) {
  const password = value.trim();

  if (password.length < 10) {
    return "Use at least 10 characters.";
  }

  if (!/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/\d/.test(password)) {
    return "Include uppercase, lowercase, and a number.";
  }

  return null;
}

export function getAuthActionMessage(action: "login" | "signup" | "forgot-password" | "update-password") {
  switch (action) {
    case "login":
      return "We couldn't sign you in with those details.";
    case "signup":
      return "We couldn't create your account right now.";
    case "forgot-password":
      return "We couldn't send a reset email right now.";
    case "update-password":
      return "We couldn't update your password right now.";
  }
}

export function buildSafeOriginUrl(pathname: string) {
  return new URL(pathname, window.location.origin).toString();
}

export function getAttemptCooldownMessage(action: CooldownKey) {
  const seconds = Math.ceil(ATTEMPT_WINDOWS[action] / 1000);
  return `Please wait ${seconds} seconds before trying again.`;
}

export function ensureAttemptCooldown(action: CooldownKey) {
  try {
    const key = `auth-attempt:${action}`;
    const lastAttempt = Number(window.sessionStorage.getItem(key) ?? 0);
    const now = Date.now();

    if (now - lastAttempt < ATTEMPT_WINDOWS[action]) {
      return getAttemptCooldownMessage(action);
    }

    window.sessionStorage.setItem(key, String(now));
    return null;
  } catch {
    return null;
  }
}
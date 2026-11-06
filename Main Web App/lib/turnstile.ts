type TurnstileVerificationResult = {
  success: boolean;
  message?: string;
};

const isProduction = process.env.NODE_ENV === "production";

export const hasTurnstileEnv = Boolean(
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY && process.env.TURNSTILE_SECRET_KEY,
);

export async function verifyTurnstileToken(
  token: string,
  remoteIp?: string,
): Promise<TurnstileVerificationResult> {
  if (!hasTurnstileEnv) {
    if (isProduction) {
      return {
        success: false,
        message: "Bot protection is not configured for this deployment.",
      };
    }

    return { success: true };
  }

  if (!token) {
    return {
      success: false,
      message: "Complete the bot check and try again.",
    };
  }

  const response = await fetch(
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        secret: process.env.TURNSTILE_SECRET_KEY!,
        response: token,
        ...(remoteIp ? { remoteip: remoteIp } : {}),
      }),
      cache: "no-store",
    },
  );

  if (!response.ok) {
    return {
      success: false,
      message: "Bot protection could not be verified. Please retry.",
    };
  }

  const payload = (await response.json()) as {
    success?: boolean;
  };

  if (!payload.success) {
    return {
      success: false,
      message: "Bot protection could not be verified. Please retry.",
    };
  }

  return { success: true };
}
import { createBrowserClient } from "@supabase/ssr";
import { hasEnvVars, supabasePublishableKey, supabaseUrl } from "@/lib/utils";

export function createClient() {
  if (!hasEnvVars) {
    throw new Error("Supabase client is not configured. Missing NEXT_PUBLIC_SUPABASE_URL or publishable key.");
  }

  return createBrowserClient(
    supabaseUrl,
    supabasePublishableKey,
    {
      auth: {
        // Middleware/server routes handle token refresh on navigation.
        // Disabling browser auto-refresh avoids noisy retry loops when offline
        // or when the Supabase endpoint is unreachable.
        autoRefreshToken: false,
      },
    },
  );
}

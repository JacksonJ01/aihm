import { createBrowserClient } from "@supabase/ssr";
import { supabasePublishableKey, supabaseUrl } from "@/lib/utils";

export function createClient() {
  return createBrowserClient(
    supabaseUrl,
    supabasePublishableKey,
  );
}

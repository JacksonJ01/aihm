import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";
import { hasEnvVars } from "@/lib/utils";

/**
 * Safe deployment diagnostic. It reports configuration state without exposing
 * the Supabase URL, keys, cookies, or database contents.
 */
export async function GET() {
  if (!hasEnvVars) {
    return NextResponse.json({
      status: "guest-mode",
      supabaseConfigured: false,
      authServiceReachable: false,
      message: "The app is usable as a guest. Add Supabase environment variables to enable accounts.",
    });
  }

  try {
    const supabase = await createClient();
    const { error } = await supabase.auth.getSession();

    return NextResponse.json({
      status: error ? "degraded" : "ok",
      supabaseConfigured: true,
      authServiceReachable: !error,
      message: error ? "Guest mode remains available, but Supabase authentication needs attention." : "Guest mode and Supabase authentication are available.",
    }, { status: error ? 503 : 200 });
  } catch {
    return NextResponse.json({
      status: "degraded",
      supabaseConfigured: true,
      authServiceReachable: false,
      message: "Guest mode remains available, but the Supabase connection could not be checked.",
    }, { status: 503 });
  }
}

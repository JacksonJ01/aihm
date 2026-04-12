import { createClient } from "@/lib/supabase/server";
import { hasEnvVars } from "@/lib/utils";
import { NextResponse, type NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const loginUrl = new URL("/auth/login", request.url);

  if (!hasEnvVars) {
    return NextResponse.redirect(loginUrl);
  }

  const supabase = await createClient();
  await supabase.auth.signOut();

  return NextResponse.redirect(loginUrl);
}
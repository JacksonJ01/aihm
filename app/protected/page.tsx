import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { Suspense } from "react";

async function UserDetails() {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getClaims();

  if (error || !data?.claims) {
    redirect("/auth/login");
  }

  return JSON.stringify(
    {
      email: data.claims.email,
      session: "Active",
    },
    null,
    2,
  );
}

export default function ProtectedPage() {
  return (
    <div className="flex-1 w-full flex flex-col gap-12">
      <div className="w-full">
        <div className="bg-accent text-sm p-3 px-5 rounded-md text-foreground flex gap-3 items-center">
          <ShieldCheck size="16" strokeWidth={2} />
          Your account is signed in and ready to continue.
        </div>
      </div>
      <div className="flex flex-col gap-2 items-start">
        <h2 className="font-bold text-2xl mb-4">Account status</h2>
        <pre className="text-xs font-mono p-3 rounded border max-h-32 overflow-auto">
          <Suspense>
            <UserDetails />
          </Suspense>
        </pre>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
          <div className="flex items-center gap-3 text-lg font-semibold text-foreground">
            <CheckCircle2 className="h-5 w-5 text-primary" />
            Account access confirmed
          </div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            You can move into profile, programs, workouts, and progress with your active session in place.
          </p>
        </div>
        <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
          <div className="text-lg font-semibold text-foreground">Next places to check</div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Head to your profile to update preferences, or open workouts to start a new session.
          </p>
        </div>
      </div>
    </div>
  );
}

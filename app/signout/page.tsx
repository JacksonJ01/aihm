import Link from "next/link";

import { AppPage, PageHero, SectionCard } from "@/components/app/page-primitives";
import { LogoutButton } from "@/components/logout-button";

export default function SignOutPage() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Sign out"
        title="Leave the session cleanly when you are done."
        description="Sign out from here when you want to close the current session and return to the login flow."
        actions={[
          { href: "/profile", label: "Back to profile", secondary: true },
        ]}
        aside={
          <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
            <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Session status</div>
            <p className="mt-3 text-sm leading-6 text-white/70">
              Signing out returns you to the authentication flow and clears the active client session.
            </p>
          </div>
        }
      />

      <SectionCard
        eyebrow="Confirm"
        title="Ready to sign out?"
        description="Choose sign out to end the current session, or return to profile if you want to stay in the app."
        className="mx-auto max-w-3xl"
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <LogoutButton />
          <Link href="/profile" className="button-secondary">
            Cancel and return
          </Link>
        </div>
      </SectionCard>
    </AppPage>
  );
}
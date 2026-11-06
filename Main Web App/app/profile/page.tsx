import { BadgeCheck, CircleUserRound, SlidersHorizontal, Target } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  PageHero,
  StatCard,
} from "@/components/app/page-primitives";
import { ProfileInlineEditor } from "@/components/app/profile-inline-editor";
import { getProfileData } from "../../lib/site-data";
import { Suspense } from "react";

function ProfilePageFallback() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Profile"
        title="Set up your profile so training can personalize around you."
        description="Loading your profile, preferences, and account details."
      />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Weekly goal" value="--" detail="Loading weekly training targets." icon={Target} />
        <StatCard label="Primary focus" value="Loading" detail="Loading current focus area." icon={BadgeCheck} />
        <StatCard label="Experience" value="Loading" detail="Loading profile level." icon={CircleUserRound} />
        <StatCard label="Camera mode" value="--" detail="Loading workout preferences." icon={SlidersHorizontal} />
      </section>
    </AppPage>
  );
}

async function ProfilePageContent() {
  const profileData = await getProfileData();
  const { profile, email } = profileData.data;
  const isProfileEmpty = profileData.source === "empty";

  return (
    <AppPage>
      <PageHero
        eyebrow="Profile"
        title={isProfileEmpty ? "Set up your profile so training can personalize around you." : `${profile.displayName} keeps training centered around ${profile.focus.toLowerCase()}.`}
        description={isProfileEmpty ? "Profile details, preferences, and account information will appear here once you save them for this account." : "Profile details, preferences, and account information stay together here for quick review and updates."}
        actions={[
          { href: "/help", label: "Open help", secondary: true },
          { href: "/progress", label: "Review progress" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={profileData.source}
              viewerState={profileData.viewerState}
              viewerEmail={profileData.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">
                {profileData.viewerState === "authenticated" ? "Account" : "Preview account"}
              </div>
              <div className="mt-3 text-xl font-semibold tracking-[-0.03em]">{email || profileData.viewerEmail || "Signed-in account"}</div>
              <p className="mt-3 text-sm leading-6 text-white/70">
                {isProfileEmpty ? "Save your first profile details below to personalize workouts, programs, and preferences." : `Training goal: ${profile.primaryGoal}`}
              </p>
            </div>
          </>
        }
      />

      <ProfileInlineEditor profile={profile} />
    </AppPage>
  );
}

export default function ProfilePage() {
  return (
    <Suspense fallback={<ProfilePageFallback />}>
      <ProfilePageContent />
    </Suspense>
  );
}

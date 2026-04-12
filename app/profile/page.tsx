import { BadgeCheck, CircleUserRound, SlidersHorizontal, Target } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  InlineLink,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { ProfileSettingsForm } from "@/components/app/profile-settings-form";
import { getProfileData } from "@/lib/site-data";
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
  const { profile, preferences, email } = profileData.data;
  const isProfileEmpty = profileData.source === "empty";

  return (
    <AppPage>
      <PageHero
        eyebrow="Profile"
        title={isProfileEmpty ? "Set up your profile so training can personalize around you." : `${profile.display_name} keeps training centered around ${profile.focus_area.toLowerCase()}.`}
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
                {isProfileEmpty ? "Save your first profile details below to personalize workouts, programs, and preferences." : `Training goal: ${profile.training_goal}`}
              </p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Weekly goal" value={isProfileEmpty ? "Not set" : `${profile.weekly_goal} sessions`} detail="How much training this profile is trying to hold each week." icon={Target} />
        <StatCard label="Primary focus" value={isProfileEmpty ? "Choose one" : profile.focus_area} detail="The dominant lens currently shaping programs and workouts." icon={BadgeCheck} />
        <StatCard label="Experience" value={isProfileEmpty ? "Add level" : profile.level} detail="Useful context for how aggressive plans and cues should feel." icon={CircleUserRound} />
        <StatCard label="Camera mode" value={isProfileEmpty ? "Not set" : preferences.camera_enabled ? "Enabled" : "Off"} detail="Live tracking preferences for workout sessions." icon={SlidersHorizontal} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard
          eyebrow="Profile summary"
          title="Training identity"
          description="A concise account of what the user is working toward and how the app should frame decisions."
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Goal</div>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {profile.training_goal || "Add a training goal to tailor recommendations and keep the rest of the app aligned with this account."}
              </p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Bio</div>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {profile.bio || "Tell the app a bit about how you train so profile and recovery decisions have some context."}
              </p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Location</div>
              <div className="mt-3 text-xl font-semibold tracking-[-0.03em] text-foreground">{profile.city || "Add city"}</div>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Preferred window</div>
              <div className="mt-3 text-xl font-semibold tracking-[-0.03em] text-foreground">{preferences.preferred_time}</div>
            </div>
          </div>
        </SectionCard>

        <div className="grid gap-6">
          <SectionCard
            eyebrow="Preferences"
            title="How this account trains"
            description="Preferences shape how visible cues and recovery defaults appear throughout the app."
          >
            <div className="space-y-3">
              <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
                Camera tracking: <span className="font-semibold text-foreground">{preferences.camera_enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
                Audio cues: <span className="font-semibold text-foreground">{preferences.audio_cues ? "Enabled" : "Disabled"}</span>
              </div>
              <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
                Recovery day: <span className="font-semibold text-foreground">{preferences.recovery_day}</span>
              </div>
            </div>
            <div className="mt-5">
              <InlineLink href="/help">Open help and setup</InlineLink>
            </div>
          </SectionCard>

          <ProfileSettingsForm profile={profile} preferences={preferences} />
        </div>
      </section>
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

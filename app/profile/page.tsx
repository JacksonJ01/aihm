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

export default async function ProfilePage() {
  const profileData = await getProfileData();
  const { profile, preferences, email } = profileData.data;

  return (
    <AppPage>
      <PageHero
        eyebrow="Profile"
        title={`${profile.display_name} keeps training centered around ${profile.focus_area.toLowerCase()}.`}
        description="The profile page should explain the athlete behind the dashboard, surface preferences that shape the experience, and make nearby actions easy to find."
        actions={[
          { href: "/help", label: "Open help", secondary: true },
          { href: "/progress", label: "Review progress" },
        ]}
        aside={
          <>
            <DataSourceNotice source={profileData.source} tables={["user_profiles", "training_preferences"]} />
            <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Account</div>
              <div className="mt-3 text-xl font-semibold tracking-[-0.03em]">{email}</div>
              <p className="mt-3 text-sm leading-6 text-white/70">Training goal: {profile.training_goal}</p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Weekly goal" value={`${profile.weekly_goal} sessions`} detail="How much training this profile is trying to hold each week." icon={Target} />
        <StatCard label="Primary focus" value={profile.focus_area} detail="The dominant lens currently shaping programs and workouts." icon={BadgeCheck} />
        <StatCard label="Experience" value={profile.level} detail="Useful context for how aggressive plans and cues should feel." icon={CircleUserRound} />
        <StatCard label="Camera mode" value={preferences.camera_enabled ? "Enabled" : "Off"} detail="Whether the profile expects live pose guidance as part of regular sessions." icon={SlidersHorizontal} />
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
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{profile.training_goal}</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Bio</div>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{profile.bio}</p>
            </div>
            <div className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Location</div>
              <div className="mt-3 text-xl font-semibold tracking-[-0.03em] text-foreground">{profile.city}</div>
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
                Camera guidance: <span className="font-semibold text-foreground">{preferences.camera_enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
                Audio cues: <span className="font-semibold text-foreground">{preferences.audio_cues ? "Enabled" : "Disabled"}</span>
              </div>
              <div className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
                Recovery day: <span className="font-semibold text-foreground">{preferences.recovery_day}</span>
              </div>
            </div>
            <div className="mt-5">
              <InlineLink href="/help">Need account or setup guidance?</InlineLink>
            </div>
          </SectionCard>

          <ProfileSettingsForm profile={profile} preferences={preferences} />
        </div>
      </section>
    </AppPage>
  );
}

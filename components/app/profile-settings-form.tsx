import { updateProfileAction } from "@/app/profile/actions";
import type { UserProfiles, WorkoutPref } from "@/lib/site-data";

type ProfileSettingsFormProps = {
  profile: UserProfiles;
  preferences: WorkoutPref;
};

export function ProfileSettingsForm({ profile, preferences }: ProfileSettingsFormProps) {
  return (
    <form action={updateProfileAction} className="space-y-5 rounded-[28px] border border-black/10 bg-white/72 px-5 py-5">
      <div>
        <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Edit settings</div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Update the details that shape how your training profile, preferences, and recommendations are presented.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Display name</span>
          <input name="display_name" defaultValue={profile.display_name} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Focus area</span>
          <input name="focus_area" defaultValue={profile.focus_area} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Level</span>
          <input name="level" defaultValue={profile.level} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">City</span>
          <input name="city" defaultValue={profile.city} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Weekly goal</span>
          <input name="weekly_goal" type="number" min={1} defaultValue={profile.weekly_goal} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Preferred time</span>
          <input name="preferred_time" defaultValue={preferences.preferred_time} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2 md:col-span-2">
          <span className="text-sm font-medium text-foreground">Training goal</span>
          <textarea name="training_goal" defaultValue={profile.training_goal} rows={3} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
        <label className="space-y-2 md:col-span-2">
          <span className="text-sm font-medium text-foreground">Bio</span>
          <textarea name="bio" defaultValue={profile.bio} rows={4} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex items-center gap-3 rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground">
          <input type="checkbox" name="camera_enabled" defaultChecked={preferences.camera_enabled} className="h-4 w-4" />
          Camera guidance enabled
        </label>
        <label className="flex items-center gap-3 rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground">
          <input type="checkbox" name="audio_cues" defaultChecked={preferences.audio_cues} className="h-4 w-4" />
          Audio cues enabled
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-foreground">Recovery day</span>
          <input name="recovery_day" defaultValue={preferences.recovery_day} className="w-full rounded-2xl border border-black/10 bg-background/60 px-4 py-3 text-sm text-foreground outline-none" />
        </label>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <button type="submit" className="button-primary">
          Save settings
        </button>
        <p className="text-sm leading-6 text-muted-foreground">
          Changes made here help keep your workouts, programs, and profile aligned with how you like to train.
        </p>
      </div>
    </form>
  );
}
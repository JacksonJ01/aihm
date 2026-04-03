import { hasEnvVars } from "@/lib/utils";
import { createClient } from "@/lib/supabase/server";

export type DataSource = "live" | "sample";

type PageResult<T> = {
  data: T;
  source: DataSource;
};

export type ProgramCatalogItem = {
  id: string;
  title: string;
  summary: string;
  focus_area: string;
  difficulty: string;
  duration_weeks: number;
  sessions_per_week: number;
  coach_note: string;
  featured: boolean;
};

export type UserProgramItem = {
  id: string;
  title: string;
  focus_area: string;
  status: string;
  progress_percent: number;
  next_session: string;
  streak_days: number;
  completed_sessions: number;
  weekly_target: number;
  weekly_completed: number;
};

export type WorkoutSessionItem = {
  id: string;
  title: string;
  focus_area: string;
  duration_minutes: number;
  effort: string;
  score: number;
  completed_at: string;
  notes: string;
};

export type CommunityPostItem = {
  id: string;
  author_name: string;
  category: string;
  title: string;
  excerpt: string;
  reply_count: number;
  like_count: number;
  created_at: string;
  is_pinned: boolean;
};

export type CommunityChallengeItem = {
  id: string;
  title: string;
  description: string;
  cadence: string;
  participants: number;
  starts_on: string;
  ends_on: string;
};

export type FriendshipItem = {
  id: string;
  friend_name: string;
  status: string;
  shared_streak: number;
  last_workout_at: string;
  focus_area: string;
};

export type NotificationItem = {
  id: string;
  title: string;
  message: string;
  category: string;
  cta_label: string | null;
  cta_href: string | null;
  is_read: boolean;
  created_at: string;
};

export type UserProfileItem = {
  display_name: string;
  training_goal: string;
  weekly_goal: number;
  focus_area: string;
  level: string;
  city: string;
  bio: string;
};

export type TrainingPreferenceItem = {
  camera_enabled: boolean;
  audio_cues: boolean;
  preferred_time: string;
  recovery_day: string;
};

type AuthContext = {
  userId?: string;
  email?: string;
  supabase?: Awaited<ReturnType<typeof createClient>>;
};

const fallbackPrograms: ProgramCatalogItem[] = [
  {
    id: "prog-1",
    title: "Strength Foundation",
    summary: "A four-week base plan for rebuilding lifting rhythm, movement quality, and upper or lower split consistency.",
    focus_area: "Strength",
    difficulty: "Intermediate",
    duration_weeks: 4,
    sessions_per_week: 4,
    coach_note: "Use this when you want a repeatable weekly structure with enough room for recovery.",
    featured: true,
  },
  {
    id: "prog-2",
    title: "Mobility Reset",
    summary: "Short guided sessions that improve range, core control, and joint prep before harder training blocks.",
    focus_area: "Mobility",
    difficulty: "Beginner",
    duration_weeks: 3,
    sessions_per_week: 5,
    coach_note: "Best for users returning from inconsistency or spending long hours seated.",
    featured: true,
  },
  {
    id: "prog-3",
    title: "Conditioning Builder",
    summary: "Progressive intervals and full-body circuits designed to raise work capacity without losing structure.",
    focus_area: "Conditioning",
    difficulty: "Advanced",
    duration_weeks: 6,
    sessions_per_week: 3,
    coach_note: "Works well alongside a primary strength block when your weekly capacity is stable.",
    featured: false,
  },
];

const fallbackUserPrograms: UserProgramItem[] = [
  {
    id: "user-prog-1",
    title: "Strength Foundation",
    focus_area: "Strength",
    status: "On track",
    progress_percent: 68,
    next_session: "2026-04-04T18:00:00.000Z",
    streak_days: 4,
    completed_sessions: 11,
    weekly_target: 4,
    weekly_completed: 3,
  },
  {
    id: "user-prog-2",
    title: "Mobility Reset",
    focus_area: "Mobility",
    status: "Recovery week",
    progress_percent: 42,
    next_session: "2026-04-05T12:00:00.000Z",
    streak_days: 2,
    completed_sessions: 6,
    weekly_target: 5,
    weekly_completed: 2,
  },
];

const fallbackSessions: WorkoutSessionItem[] = [
  {
    id: "session-1",
    title: "Mobility + Core Reset",
    focus_area: "Mobility",
    duration_minutes: 28,
    effort: "Moderate",
    score: 92,
    completed_at: "2026-04-02T18:15:00.000Z",
    notes: "Camera alignment stayed stable after the first three minutes.",
  },
  {
    id: "session-2",
    title: "Upper Push Strength",
    focus_area: "Strength",
    duration_minutes: 44,
    effort: "High",
    score: 88,
    completed_at: "2026-03-31T18:05:00.000Z",
    notes: "Good cadence, but shoulder position drifted during the last set.",
  },
  {
    id: "session-3",
    title: "Tempo Conditioning Ladder",
    focus_area: "Conditioning",
    duration_minutes: 35,
    effort: "High",
    score: 85,
    completed_at: "2026-03-29T17:40:00.000Z",
    notes: "Strong finish and consistent breathing on later rounds.",
  },
  {
    id: "session-4",
    title: "Recovery Mobility Flow",
    focus_area: "Recovery",
    duration_minutes: 22,
    effort: "Low",
    score: 95,
    completed_at: "2026-03-27T12:30:00.000Z",
    notes: "Best posture score this week.",
  },
];

const fallbackPosts: CommunityPostItem[] = [
  {
    id: "post-1",
    author_name: "Nina R.",
    category: "Form check",
    title: "What cues help you keep your rib cage stacked during overhead work?",
    excerpt: "I keep losing position in the second half of a set and want one cue that keeps me organized without overthinking it.",
    reply_count: 14,
    like_count: 29,
    created_at: "2026-04-03T07:00:00.000Z",
    is_pinned: true,
  },
  {
    id: "post-2",
    author_name: "Miles T.",
    category: "Challenge log",
    title: "Day 12 of the morning mobility streak",
    excerpt: "Ten minutes has been enough to keep the habit intact, and the app cues are making the start feel easier.",
    reply_count: 8,
    like_count: 21,
    created_at: "2026-04-02T14:00:00.000Z",
    is_pinned: false,
  },
  {
    id: "post-3",
    author_name: "Avery K.",
    category: "Programs",
    title: "How are people combining conditioning with Strength Foundation?",
    excerpt: "I want to keep two conditioning sessions each week without flattening recovery on the main lifting days.",
    reply_count: 11,
    like_count: 17,
    created_at: "2026-04-01T18:45:00.000Z",
    is_pinned: false,
  },
];

const fallbackChallenges: CommunityChallengeItem[] = [
  {
    id: "challenge-1",
    title: "7-Day Consistency Sprint",
    description: "Complete one focused session each day, even if it is only fifteen minutes.",
    cadence: "Daily",
    participants: 184,
    starts_on: "2026-04-01",
    ends_on: "2026-04-07",
  },
  {
    id: "challenge-2",
    title: "Posture Reset Week",
    description: "Stack mobility, breathing, and camera-assisted alignment checks into a single recovery block.",
    cadence: "5 sessions",
    participants: 92,
    starts_on: "2026-04-08",
    ends_on: "2026-04-14",
  },
];

const fallbackFriends: FriendshipItem[] = [
  {
    id: "friend-1",
    friend_name: "Jordan P.",
    status: "accepted",
    shared_streak: 5,
    last_workout_at: "2026-04-02T18:20:00.000Z",
    focus_area: "Strength",
  },
  {
    id: "friend-2",
    friend_name: "Camila S.",
    status: "accepted",
    shared_streak: 3,
    last_workout_at: "2026-04-01T12:05:00.000Z",
    focus_area: "Mobility",
  },
  {
    id: "friend-3",
    friend_name: "Theo M.",
    status: "pending",
    shared_streak: 0,
    last_workout_at: "2026-03-30T09:10:00.000Z",
    focus_area: "Conditioning",
  },
];

const fallbackNotifications: NotificationItem[] = [
  {
    id: "notif-1",
    title: "Tonight's session is ready",
    message: "Your next Strength Foundation workout is queued with a shoulder prep warm-up.",
    category: "Workout",
    cta_label: "Open workout",
    cta_href: "/workouts",
    is_read: false,
    created_at: "2026-04-03T08:10:00.000Z",
  },
  {
    id: "notif-2",
    title: "Jordan matched your streak",
    message: "Your accountability circle is still tied at five days. One session breaks the tie.",
    category: "Friends",
    cta_label: "View friends",
    cta_href: "/friends",
    is_read: false,
    created_at: "2026-04-02T20:00:00.000Z",
  },
  {
    id: "notif-3",
    title: "Challenge reminder",
    message: "The 7-Day Consistency Sprint closes in four days. You have completed two of seven check-ins.",
    category: "Community",
    cta_label: "Open community",
    cta_href: "/community",
    is_read: true,
    created_at: "2026-04-01T11:45:00.000Z",
  },
];

const fallbackProfile: UserProfileItem = {
  display_name: "Alex Carter",
  training_goal: "Build a stronger weekly routine with better movement quality.",
  weekly_goal: 4,
  focus_area: "Strength",
  level: "Intermediate",
  city: "Remote",
  bio: "Working toward a repeatable training cadence that balances lifting, mobility, and recovery.",
};

const fallbackPreferences: TrainingPreferenceItem = {
  camera_enabled: true,
  audio_cues: false,
  preferred_time: "Evenings",
  recovery_day: "Sunday",
};

async function getAuthContext(): Promise<AuthContext> {
  if (!hasEnvVars) {
    return {};
  }

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();

  return {
    supabase,
    userId: data?.claims?.sub,
    email: data?.claims?.email,
  };
}

async function withFallback<T>(
  fallback: T,
  loader: (context: AuthContext) => Promise<T>,
): Promise<PageResult<T>> {
  try {
    const context = await getAuthContext();

    if (!context.supabase) {
      return { data: fallback, source: "sample" };
    }

    const data = await loader(context);
    return { data, source: "live" };
  } catch {
    return { data: fallback, source: "sample" };
  }
}

export function formatLongDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatShortDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export async function getBrowseProgramsData() {
  return withFallback(fallbackPrograms, async ({ supabase }) => {
    const { data, error } = await supabase!
      .from("program_catalog")
      .select("id, title, summary, focus_area, difficulty, duration_weeks, sessions_per_week, coach_note, featured")
      .order("featured", { ascending: false })
      .order("title", { ascending: true });

    if (error) {
      throw error;
    }

    return (data as ProgramCatalogItem[]) ?? fallbackPrograms;
  });
}

export async function getProgramsData() {
  return withFallback(fallbackUserPrograms, async ({ supabase, userId }) => {
    if (!userId) {
      return fallbackUserPrograms;
    }

    const { data, error } = await supabase!
      .from("user_programs")
      .select("id, title, focus_area, status, progress_percent, next_session, streak_days, completed_sessions, weekly_target, weekly_completed")
      .eq("user_id", userId)
      .order("next_session", { ascending: true });

    if (error) {
      throw error;
    }

    return (data as UserProgramItem[]) ?? fallbackUserPrograms;
  });
}

export async function getWorkoutSessionsData() {
  return withFallback(fallbackSessions, async ({ supabase, userId }) => {
    if (!userId) {
      return fallbackSessions;
    }

    const { data, error } = await supabase!
      .from("workout_sessions")
      .select("id, title, focus_area, duration_minutes, effort, score, completed_at, notes")
      .eq("user_id", userId)
      .order("completed_at", { ascending: false })
      .limit(8);

    if (error) {
      throw error;
    }

    return (data as WorkoutSessionItem[]) ?? fallbackSessions;
  });
}

export async function getCommunityData() {
  return withFallback(
    { posts: fallbackPosts, challenges: fallbackChallenges },
    async ({ supabase }) => {
      const [{ data: posts, error: postsError }, { data: challenges, error: challengesError }] = await Promise.all([
        supabase!
          .from("community_posts")
          .select("id, author_name, category, title, excerpt, reply_count, like_count, created_at, is_pinned")
          .order("is_pinned", { ascending: false })
          .order("created_at", { ascending: false })
          .limit(6),
        supabase!
          .from("community_challenges")
          .select("id, title, description, cadence, participants, starts_on, ends_on")
          .order("starts_on", { ascending: true })
          .limit(4),
      ]);

      if (postsError || challengesError) {
        throw postsError ?? challengesError;
      }

      return {
        posts: (posts as CommunityPostItem[]) ?? fallbackPosts,
        challenges: (challenges as CommunityChallengeItem[]) ?? fallbackChallenges,
      };
    },
  );
}

export async function getFriendsData() {
  return withFallback(fallbackFriends, async ({ supabase, userId }) => {
    if (!userId) {
      return fallbackFriends;
    }

    const { data, error } = await supabase!
      .from("friendships")
      .select("id, friend_name, status, shared_streak, last_workout_at, focus_area")
      .eq("user_id", userId)
      .order("status", { ascending: true })
      .order("last_workout_at", { ascending: false });

    if (error) {
      throw error;
    }

    return (data as FriendshipItem[]) ?? fallbackFriends;
  });
}

export async function getNotificationsData() {
  return withFallback(fallbackNotifications, async ({ supabase, userId }) => {
    if (!userId) {
      return fallbackNotifications;
    }

    const { data, error } = await supabase!
      .from("notifications")
      .select("id, title, message, category, cta_label, cta_href, is_read, created_at")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(12);

    if (error) {
      throw error;
    }

    return (data as NotificationItem[]) ?? fallbackNotifications;
  });
}

export async function getProfileData() {
  return withFallback(
    {
      profile: fallbackProfile,
      preferences: fallbackPreferences,
      email: "athlete@aihm.app",
    },
    async ({ supabase, userId, email }) => {
      if (!userId) {
        return {
          profile: fallbackProfile,
          preferences: fallbackPreferences,
          email: email ?? "athlete@aihm.app",
        };
      }

      const [{ data: profile, error: profileError }, { data: preferences, error: preferencesError }] = await Promise.all([
        supabase!
          .from("user_profiles")
          .select("display_name, training_goal, weekly_goal, focus_area, level, city, bio")
          .eq("user_id", userId)
          .maybeSingle(),
        supabase!
          .from("training_preferences")
          .select("camera_enabled, audio_cues, preferred_time, recovery_day")
          .eq("user_id", userId)
          .maybeSingle(),
      ]);

      if (profileError || preferencesError) {
        throw profileError ?? preferencesError;
      }

      return {
        profile: (profile as UserProfileItem) ?? fallbackProfile,
        preferences: (preferences as TrainingPreferenceItem) ?? fallbackPreferences,
        email: email ?? "athlete@aihm.app",
      };
    },
  );
}
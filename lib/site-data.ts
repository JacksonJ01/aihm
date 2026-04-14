import { hasEnvVars } from "@/lib/utils";
import { createClient } from "@/lib/supabase/server";

export type DataSource = "live" | "sample" | "empty";
export type ViewerState = "authenticated" | "guest";

type PageResult<T> = {
  data: T;
  source: DataSource;
  viewerState: ViewerState;
  viewerEmail?: string;
};

export type Programs = {
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

export type UserPrograms = {
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

export type WorkoutSessions = {
  id: string;
  title: string;
  focus_area: string;
  duration_minutes: number;
  effort: string;
  score: number;
  completed_at: string;
  notes: string;
};

export type CommunityPosts = {
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

export type CommunityChallenges = {
  id: string;
  title: string;
  description: string;
  cadence: string;
  participants: number;
  starts_on: string;
  ends_on: string;
};

export type UserFriends = {
  id: string;
  friend_name: string;
  status: string;
  shared_streak: number;
  last_workout_at: string;
  focus_area: string;
};

export type Notifications = {
  id: number;
  title: string;
  message: string;
  category: string;
  cta_label: string | null;
  cta_href: string | null;
  is_read: boolean;
  created_at: string;
};

export type UserProfiles = {
  user_name: string;
  display_name: string;
  training_goal: string;
  weekly_goal: number;
  focus_area: string;
  level: string;
  city: string;
  bio: string;
};

export type WorkoutPref = {
  camera_enabled: boolean;
  audio_cues: boolean;
  preferred_time: string;
  recovery_day: string;
};

export type CommunityPostReplies = {
  id: string;
  post_id: string;
  display_name: string;
  parent_reply_id: string | null;
  body_text: string;
  is_edited: string;
  created_at: string;
  updated_at: string;
};

export type FriendConversations = {
  id: string;
  friend_id: string;
  user_one: string;
  user_two: string;
  last_message: string | null;
  created_at: string;
  updated_at: string;
};

export type FriendMessage = {
  id: string;
  conversation_id: string;
  sender_user_id: string;
  body: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  updated_at: string;
};

type AuthContext = {
  userId?: string;
  email?: string;
  supabase?: Awaited<ReturnType<typeof createClient>>;
  viewerState: ViewerState;
};

const fallbackPrograms: Programs[] = [
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


const fallbackPosts: CommunityPosts[] = [
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

const fallbackChallenges: CommunityChallenges[] = [
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

const emptyProfile: UserProfiles = {
  user_name: "",
  display_name: "Your profile",
  training_goal: "",
  weekly_goal: 0,
  focus_area: "General",
  level: "Not set",
  city: "",
  bio: "",
};

const emptyPreferences: WorkoutPref = {
  camera_enabled: false,
  audio_cues: false,
  preferred_time: "Not set",
  recovery_day: "Not set",
};

async function getAuthContext(): Promise<AuthContext> {
  if (!hasEnvVars) {
    return { viewerState: "guest" };
  }

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();

  return {
    supabase,
    userId: data?.claims?.sub,
    email: data?.claims?.email,
    viewerState: data?.claims?.sub ? "authenticated" : "guest",
  };
}

async function withFallback<T>(
  fallback: T,
  loader: (context: AuthContext) => Promise<T>,
): Promise<PageResult<T>> {
  try {
    const context = await getAuthContext();

    if (!context.supabase) {
      return {
        data: fallback,
        source: "sample",
        viewerState: context.viewerState,
        viewerEmail: context.email,
      };
    }

    const data = await loader(context);
    return {
      data,
      source: "live",
      viewerState: context.viewerState,
      viewerEmail: context.email,
    };
  } catch {
    const context = await getAuthContext().catch(() => ({ viewerState: "guest" as const }));
    return {
      data: fallback,
      source: "sample",
      viewerState: context.viewerState,
      viewerEmail: "email" in context ? context.email : undefined,
    };
  }
}

async function withPersonalizedData<T>(
  emptyValue: T,
  loader: (context: AuthContext & { userId: string; supabase: NonNullable<AuthContext["supabase"]> }) => Promise<T>,
  isEmpty: (data: T) => boolean,
): Promise<PageResult<T>> {
  const context = await getAuthContext();

  if (!context.supabase || !context.userId) {
    return {
      data: emptyValue,
      source: "empty",
      viewerState: context.viewerState,
      viewerEmail: context.email,
    };
  }

  try {
    const data = await loader({
      ...context,
      userId: context.userId,
      supabase: context.supabase,
    });

    return {
      data,
      source: isEmpty(data) ? "empty" : "live",
      viewerState: context.viewerState,
      viewerEmail: context.email,
    };
  } catch {
    return {
      data: emptyValue,
      source: "empty",
      viewerState: context.viewerState,
      viewerEmail: context.email,
    };
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
      .from("programs")
      .select("id, title:name, summary:description, focus_area:focus, difficulty, duration_weeks:durationWeeks, sessions_per_week:sessionsPerWeek, coach_note:coachNote, featured:isActive")
      .order("isActive", { ascending: false })
      .order("name", { ascending: true });

    if (error) {
      throw error;
    }

    return (data as Programs[]) ?? fallbackPrograms;
  });
}

export async function getProgramsData() {
  return withPersonalizedData([], async ({ supabase, userId }) => {
    const { data, error } = await supabase
      .from("userPrograms")
      .select("id, title, focus_area:focus, status, progress_percent:progressPercent, next_session:nextSession, streak_days:streakDays, completed_sessions:completedSessions, weekly_target:weeklyTarget, weekly_completed:weeklyCompleted")
      .eq("userID", userId)
      .order("nextSession", { ascending: true });

    if (error) {
      throw error;
    }

    return (data as UserPrograms[]) ?? [];
  }, (data) => data.length === 0);
}

export async function getWorkoutSessionsData() {
  return withPersonalizedData([], async ({ supabase, userId }) => {
    const { data, error } = await supabase
      .from("workoutSessions")
      .select("id, title:name, focus_area:focus, duration_minutes:durationMin, effort, score, completed_at:created_at, notes:userNotes")
      .eq("userID", userId)
      .order("created_at", { ascending: false })
      .limit(8);

    if (error) {
      throw error;
    }

    return (data as WorkoutSessions[]) ?? [];
  }, (data) => data.length === 0);
}

export async function getCommunityData() {
  return withFallback(
    { posts: fallbackPosts, challenges: fallbackChallenges },
    async ({ supabase }) => {
      const [{ data: posts, error: postsError }, { data: challenges, error: challengesError }] = await Promise.all([
        supabase!
          .from("communityPosts")
          .select("id, author_name:displayName, category, title, excerpt, reply_count:replyCount, like_count:likeCount, created_at:createdAt, is_pinned:isPinned")
          .order("isPinned", { ascending: false })
          .order("createdAt", { ascending: false })
          .limit(6),
        supabase!
          .from("communityChallenges")
          .select("id, title, description, cadence, participants, starts_on:startsOnDate, ends_on:endOfDate")
          .order("startsOnDate", { ascending: true })
          .limit(4),
      ]);

      if (postsError || challengesError) {
        throw postsError ?? challengesError;
      }

      return {
        posts: (posts as CommunityPosts[]) ?? fallbackPosts,
        challenges: (challenges as CommunityChallenges[]) ?? fallbackChallenges,
      };
    },
  );
}

export async function getFriendsData() {
  return withPersonalizedData([], async ({ supabase, userId }) => {
    const { data, error } = await supabase
      .from("userFriends")
      .select("id, friend_name:friendName, status, shared_streak:sharedStreak, last_workout_at:lastWorkoutAt, focus_area:focus")
      .eq("userID", userId)
      .order("status", { ascending: true })
      .order("lastWorkoutAt", { ascending: false });

    if (error) {
      throw error;
    }

    return (data as UserFriends[]) ?? [];
  }, (data) => data.length === 0);
}

export async function getNotificationsData() {
  return withPersonalizedData([], async ({ supabase, userId }) => {
    const { data, error } = await supabase
      .from("notifications")
      .select("id, title, message, category, cta_label:label, cta_href:link, is_read:isRead, created_at:createdAt")
      .eq("userID", userId)
      .order("createdAt", { ascending: false })
      .limit(12);

    if (error) {
      throw error;
    }

    return ((data as Notifications[]) ?? []).map((notification) => ({
      ...notification,
      cta_href: notification.cta_href?.startsWith("/") && !notification.cta_href.startsWith("//")
        ? notification.cta_href
        : null,
    }));
  }, (data) => data.length === 0);
}

export async function getProfileData() {
  return withPersonalizedData(
    {
      profile: emptyProfile,
      preferences: emptyPreferences,
      email: "",
    },
    async ({ supabase, userId, email }) => {
      const [{ data: profile, error: profileError }, { data: preferences, error: preferencesError }] = await Promise.all([
        supabase
          .from("userProfiles")
          .select("user_name:userName, display_name:displayName, training_goal:primaryGoal, weekly_goal:weeklyGoal, focus_area:focus, level:expLevel, city, bio")
          .eq("email", email ?? "")
          .maybeSingle(),
        supabase
          .from("workoutPref")
          .select("camera_enabled:camEnabled, audio_cues:audioEnabled, preferred_time:timePref, recovery_day:recoveryDay")
          .eq("userID", userId)
          .maybeSingle(),
      ]);

      if (profileError || preferencesError) {
        throw profileError ?? preferencesError;
      }

      return {
        profile: (profile as UserProfiles) ?? emptyProfile,
        preferences: (preferences as WorkoutPref) ?? emptyPreferences,
        email: email ?? "",
      };
    },
    (data) => !data.email && !data.profile.training_goal && !data.profile.bio,
  );
}
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
  slug: string;
  name: string;
  description: string;
  focus: string;
  difficulty: string;
  durationWeeks: number;
  sessionsPerWeek: number;
  coachNote: string;
  isActive: boolean;
  usersNum: number;
};

export type UserPrograms = {
  id: string;
  title: string;
  focus: string;
  status: string;
  progressPercent: number;
  nextSession: string;
  streakDays: number;
  completedSessions: number;
  weeklyTarget: number;
  weeklyCompleted: number;
};

export type WorkoutSessions = {
  id: string;
  name: string;
  focus: string;
  durationMin: number;
  effort: string;
  score: number;
  createdAt: string;
  userNotes: string;
};

export type CommunityPosts = {
  id: string;
  displayName: string;
  category: string;
  title: string;
  excerpt: string;
  replyCount: number;
  likeCount: number;
  createdAt: string;
  isPinned: boolean;
};

export type CommunityChallenges = {
  id: string;
  title: string;
  description: string;
  cadence: string;
  participants: number;
  startsOnDate: string;
  endOfDate: string;
};

export type UserFriends = {
  id: string;
  friendName: string;
  status: string;
  sharedStreak: number;
  lastWorkoutAt: string;
  focus: string;
};

export type Notifications = {
  id: number;
  title: string;
  message: string;
  category: string;
  label: string | null;
  link: string | null;
  isRead: boolean;
  createdAt: string;
};

export type UserProfiles = {
  userName: string;
  displayName: string;
  primaryGoal: string;
  weeklyGoal: number;
  focus: string;
  expLevel: string;
  city: string;
  bio: string;
};

export type WorkoutPref = {
  camEnabled: boolean;
  audioEnabled: boolean;
  timePref: string;
  recoveryDay: string;
};

export type CommunityPostReplies = {
  id: string;
  postID: string;
  displayName: string;
  parentReplyID: string | null;
  bodyText: string;
  isEdited: string;
  createdAt: string;
  updatedAt: string;
};

export type FriendConversations = {
  id: string;
  friendID: string;
  userOne: string;
  userTwo: string;
  lastMessage: string | null;
  createdAt: string;
  updatedAt: string;
};

export type FriendMessage = {
  id: string;
  conversationID: string;
  senderUserID: string;
  body: string;
  isRead: boolean;
  readAt: string | null;
  createdAt: string;
  updatedAt: string;
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
    slug: "strength-foundation",
    name: "Strength Foundation",
    description: "A four-week base plan for rebuilding lifting rhythm, movement quality, and upper or lower split consistency.",
    focus: "Strength",
    difficulty: "Intermediate",
    durationWeeks: 4,
    sessionsPerWeek: 4,
    coachNote: "Use this when you want a repeatable weekly structure with enough room for recovery.",
    isActive: true,
    usersNum: 0,
  },
  {
    id: "prog-2",
    slug: "mobility-reset",
    name: "Mobility Reset",
    description: "Short guided sessions that improve range, core control, and joint prep before harder training blocks.",
    focus: "Mobility",
    difficulty: "Beginner",
    durationWeeks: 3,
    sessionsPerWeek: 5,
    coachNote: "Best for users returning from inconsistency or spending long hours seated.",
    isActive: true,
    usersNum: 0,
  },
  {
    id: "prog-3",
    slug: "conditioning-builder",
    name: "Conditioning Builder",
    description: "Progressive intervals and full-body circuits designed to raise work capacity without losing structure.",
    focus: "Conditioning",
    difficulty: "Advanced",
    durationWeeks: 6,
    sessionsPerWeek: 3,
    coachNote: "Works well alongside a primary strength block when your weekly capacity is stable.",
    isActive: false,
    usersNum: 0,
  },
];

const fallbackPosts: CommunityPosts[] = [
  {
    id: "post-1",
    displayName: "Nina R.",
    category: "Form check",
    title: "What cues help you keep your rib cage stacked during overhead work?",
    excerpt: "I keep losing position in the second half of a set and want one cue that keeps me organized without overthinking it.",
    replyCount: 14,
    likeCount: 29,
    createdAt: "2026-04-03T07:00:00.000Z",
    isPinned: true,
  },
  {
    id: "post-2",
    displayName: "Miles T.",
    category: "Challenge log",
    title: "Day 12 of the morning mobility streak",
    excerpt: "Ten minutes has been enough to keep the habit intact, and the app cues are making the start feel easier.",
    replyCount: 8,
    likeCount: 21,
    createdAt: "2026-04-02T14:00:00.000Z",
    isPinned: false,
  },
  {
    id: "post-3",
    displayName: "Avery K.",
    category: "Programs",
    title: "How are people combining conditioning with Strength Foundation?",
    excerpt: "I want to keep two conditioning sessions each week without flattening recovery on the main lifting days.",
    replyCount: 11,
    likeCount: 17,
    createdAt: "2026-04-01T18:45:00.000Z",
    isPinned: false,
  },
];

const fallbackChallenges: CommunityChallenges[] = [
  {
    id: "challenge-1",
    title: "7-Day Consistency Sprint",
    description: "Complete one focused session each day, even if it is only fifteen minutes.",
    cadence: "Daily",
    participants: 184,
    startsOnDate: "2026-04-01",
    endOfDate: "2026-04-07",
  },
  {
    id: "challenge-2",
    title: "Posture Reset Week",
    description: "Stack mobility, breathing, and camera-assisted alignment checks into a single recovery block.",
    cadence: "5 sessions",
    participants: 92,
    startsOnDate: "2026-04-08",
    endOfDate: "2026-04-14",
  },
];

const emptyProfile: UserProfiles = {
  userName: "",
  displayName: "Your profile",
  primaryGoal: "",
  weeklyGoal: 0,
  focus: "General",
  expLevel: "Not set",
  city: "",
  bio: "",
};

const emptyPreferences: WorkoutPref = {
  camEnabled: false,
  audioEnabled: false,
  timePref: "Not set",
  recoveryDay: "Not set",
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
      .select("id, slug, name, description, focus, difficulty, durationWeeks, sessionsPerWeek, coachNote, isActive, usersNum")
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
      .select("id, title, focus, status, progressPercent, nextSession, streakDays, completedSessions, weeklyTarget, weeklyCompleted")
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
      .select("id, name, focus, durationMin, effort, score, createdAt, userNotes")
      .eq("userID", userId)
      .order("createdAt", { ascending: false })
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
          .select("id, displayName, category, title, excerpt, replyCount, likeCount, createdAt, isPinned")
          .order("isPinned", { ascending: false })
          .order("createdAt", { ascending: false })
          .limit(6),
        supabase!
          .from("communityChallenges")
          .select("id, title, description, cadence, participants, startsOnDate, endOfDate")
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
      .select("id, friendName, status, sharedStreak, lastWorkoutAt, focus")
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
      .select("id, title, message, category, label, link, isRead, createdAt")
      .eq("userID", userId)
      .order("createdAt", { ascending: false })
      .limit(12);

    if (error) {
      throw error;
    }

    return ((data as Notifications[]) ?? []).map((notification) => ({
      ...notification,
      link: notification.link?.startsWith("/") && !notification.link.startsWith("//")
        ? notification.link
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
          .select("userName, displayName, primaryGoal, weeklyGoal, focus, expLevel, city, bio")
          .eq("email", email ?? "")
          .maybeSingle(),
        supabase
          .from("workoutPref")
          .select("camEnabled, audioEnabled, timePref, recoveryDay")
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
    (data) => !data.email && !data.profile.primaryGoal && !data.profile.bio,
  );
}

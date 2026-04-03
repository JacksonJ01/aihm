create extension if not exists "pgcrypto";

create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  training_goal text not null,
  weekly_goal integer not null default 4 check (weekly_goal > 0),
  focus_area text not null,
  level text not null,
  city text not null default 'Remote',
  bio text not null default '',
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.training_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  camera_enabled boolean not null default true,
  audio_cues boolean not null default false,
  preferred_time text not null default 'Evenings',
  recovery_day text not null default 'Sunday',
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.program_catalog (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  slug text not null unique,
  summary text not null,
  focus_area text not null,
  difficulty text not null,
  duration_weeks integer not null check (duration_weeks > 0),
  sessions_per_week integer not null check (sessions_per_week > 0),
  coach_note text not null,
  featured boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.user_programs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  program_id uuid references public.program_catalog(id) on delete set null,
  title text not null,
  focus_area text not null,
  status text not null,
  progress_percent integer not null default 0 check (progress_percent between 0 and 100),
  next_session timestamptz not null,
  streak_days integer not null default 0,
  completed_sessions integer not null default 0,
  weekly_target integer not null default 3,
  weekly_completed integer not null default 0,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.workout_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  program_id uuid references public.program_catalog(id) on delete set null,
  title text not null,
  focus_area text not null,
  duration_minutes integer not null check (duration_minutes > 0),
  effort text not null,
  score integer not null default 0 check (score between 0 and 100),
  notes text not null default '',
  completed_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_posts (
  id uuid primary key default gen_random_uuid(),
  author_id uuid references auth.users(id) on delete set null,
  author_name text not null,
  category text not null,
  title text not null,
  excerpt text not null,
  reply_count integer not null default 0,
  like_count integer not null default 0,
  is_pinned boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_challenges (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text not null,
  cadence text not null,
  participants integer not null default 0,
  starts_on date not null,
  ends_on date not null,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.friendships (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  friend_user_id uuid references auth.users(id) on delete set null,
  friend_name text not null,
  status text not null default 'pending',
  shared_streak integer not null default 0,
  last_workout_at timestamptz not null default timezone('utc', now()),
  focus_area text not null default 'General',
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  message text not null,
  category text not null,
  cta_label text,
  cta_href text,
  is_read boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists user_profiles_set_updated_at on public.user_profiles;
create trigger user_profiles_set_updated_at
before update on public.user_profiles
for each row
execute procedure public.set_updated_at();

drop trigger if exists training_preferences_set_updated_at on public.training_preferences;
create trigger training_preferences_set_updated_at
before update on public.training_preferences
for each row
execute procedure public.set_updated_at();

alter table public.user_profiles enable row level security;
alter table public.training_preferences enable row level security;
alter table public.program_catalog enable row level security;
alter table public.user_programs enable row level security;
alter table public.workout_sessions enable row level security;
alter table public.community_posts enable row level security;
alter table public.community_challenges enable row level security;
alter table public.friendships enable row level security;
alter table public.notifications enable row level security;

drop policy if exists "users manage own profile" on public.user_profiles;
create policy "users manage own profile"
on public.user_profiles
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own preferences" on public.training_preferences;
create policy "users manage own preferences"
on public.training_preferences
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "authenticated users can read program catalog" on public.program_catalog;
create policy "authenticated users can read program catalog"
on public.program_catalog
for select
using (auth.role() = 'authenticated');

drop policy if exists "users manage own programs" on public.user_programs;
create policy "users manage own programs"
on public.user_programs
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own workout sessions" on public.workout_sessions;
create policy "users manage own workout sessions"
on public.workout_sessions
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "authenticated users can read community posts" on public.community_posts;
create policy "authenticated users can read community posts"
on public.community_posts
for select
using (auth.role() = 'authenticated');

drop policy if exists "users can create community posts" on public.community_posts;
create policy "users can create community posts"
on public.community_posts
for insert
with check (auth.uid() = author_id);

drop policy if exists "authenticated users can read community challenges" on public.community_challenges;
create policy "authenticated users can read community challenges"
on public.community_challenges
for select
using (auth.role() = 'authenticated');

drop policy if exists "users manage own friendships" on public.friendships;
create policy "users manage own friendships"
on public.friendships
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users manage own notifications" on public.notifications;
create policy "users manage own notifications"
on public.notifications
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
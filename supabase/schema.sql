create extension if not exists "pgcrypto";

create table if not exists public."userProfiles" (
  "id" uuid primary key references auth.users(id) on delete cascade,
  "userName" text not null unique,
  "displayName" text not null,
  "primaryGoal" text not null,
  "weeklyGoal" integer not null default 0 check ("weeklyGoal" >= 0),
  "focus" text not null,
  "expLevel" text not null,
  "city" text not null default '',
  "bio" text not null default '',
  "email" text not null unique,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."workoutPref" (
  "userID" uuid primary key references auth.users(id) on delete cascade,
  "camEnabled" boolean not null default true,
  "audioEnabled" boolean not null default false,
  "timePref" text not null default 'Evenings',
  "recoveryDay" text not null default 'Sunday',
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."programs" (
  "id" uuid primary key default gen_random_uuid(),
  "slug" text not null unique,
  "name" text not null unique,
  "description" text not null,
  "focus" text not null,
  "difficulty" text not null,
  "durationWeeks" integer not null check ("durationWeeks" > 0),
  "sessionsPerWeek" integer not null check ("sessionsPerWeek" > 0),
  "coachNote" text not null,
  "isActive" boolean not null default false,
  "usersNum" integer not null default 0,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."userPrograms" (
  "id" uuid primary key default gen_random_uuid(),
  "userID" uuid not null references auth.users(id) on delete cascade,
  "programID" uuid references public."programs"("id") on delete set null,
  "title" text not null,
  "focus" text not null,
  "status" text not null,
  "progressPercent" integer not null default 0 check ("progressPercent" between 0 and 100),
  "nextSession" timestamptz not null,
  "streakDays" integer not null default 0,
  "completedSessions" integer not null default 0,
  "weeklyTarget" integer not null default 3,
  "weeklyCompleted" integer not null default 0,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."workoutSessions" (
  "id" uuid primary key default gen_random_uuid(),
  "userID" uuid not null references auth.users(id) on delete cascade,
  "programID" uuid references public."programs"("id") on delete set null,
  "name" text not null,
  "focus" text not null,
  "durationMin" integer not null check ("durationMin" > 0),
  "effort" text not null,
  "score" integer not null default 0 check ("score" between 0 and 100),
  "userNotes" text not null default '',
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."communityPosts" (
  "id" uuid primary key default gen_random_uuid(),
  "userID" uuid references auth.users(id) on delete set null,
  "displayName" text not null,
  "category" text not null,
  "title" text not null,
  "excerpt" text not null,
  "replyCount" integer not null default 0,
  "likeCount" integer not null default 0,
  "isPinned" boolean not null default false,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."communityPostReplies" (
  "id" uuid primary key default gen_random_uuid(),
  "postID" uuid not null references public."communityPosts"("id") on delete cascade,
  "displayName" text not null,
  "parentReplyID" uuid references public."communityPostReplies"("id") on delete cascade,
  "bodyText" text not null,
  "isEdited" boolean not null default false,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."communityChallenges" (
  "id" uuid primary key default gen_random_uuid(),
  "title" text not null,
  "description" text not null,
  "cadence" text not null,
  "participants" integer not null default 0,
  "startsOnDate" timestamptz not null default timezone('utc', now()),
  "endOfDate" timestamptz not null default timezone('utc', now()),
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."userFriends" (
  "id" uuid primary key default gen_random_uuid(),
  "userID" uuid not null references auth.users(id) on delete cascade,
  "friendUserID" uuid references auth.users(id) on delete set null,
  "friendName" text not null,
  "status" text not null default 'pending',
  "sharedStreak" integer not null default 0,
  "lastWorkoutAt" timestamptz not null default timezone('utc', now()),
  "focus" text not null default 'General',
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."friendConversations" (
  "id" uuid primary key default gen_random_uuid(),
  "friendID" uuid not null references public."userFriends"("id") on delete cascade unique,
  "userOne" uuid not null references auth.users(id) on delete cascade,
  "userTwo" uuid not null references auth.users(id) on delete cascade,
  "lastMessage" timestamptz,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public."friendMessage" (
  "id" uuid primary key default gen_random_uuid(),
  "conversationID" uuid not null references public."friendConversations"("id") on delete cascade,
  "senderUserID" uuid not null references auth.users(id) on delete cascade,
  "body" text not null,
  "isRead" boolean not null default false,
  "readAt" timestamptz,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create table if not exists public.notifications (
  "id" bigint generated always as identity primary key,
  "userID" uuid not null references auth.users(id) on delete cascade,
  "title" text not null,
  "message" text not null,
  "category" text not null,
  "label" text,
  "link" text,
  "isRead" boolean not null default false,
  "createdAt" timestamptz not null default timezone('utc', now()),
  "updatedAt" timestamptz not null default timezone('utc', now())
);

create or replace function public."setUpdatedAt"()
returns trigger
language plpgsql
as $$
begin
  new."updatedAt" = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists "userProfiles_setUpdatedAt" on public."userProfiles";
create trigger "userProfiles_setUpdatedAt"
before update on public."userProfiles"
for each row
execute procedure public."setUpdatedAt"();

drop trigger if exists "workoutPref_setUpdatedAt" on public."workoutPref";
create trigger "workoutPref_setUpdatedAt"
before update on public."workoutPref"
for each row
execute procedure public."setUpdatedAt"();

alter table public."userProfiles" enable row level security;
alter table public."workoutPref" enable row level security;
alter table public."programs" enable row level security;
alter table public."userPrograms" enable row level security;
alter table public."workoutSessions" enable row level security;
alter table public."communityPosts" enable row level security;
alter table public."communityPostReplies" enable row level security;
alter table public."communityChallenges" enable row level security;
alter table public."userFriends" enable row level security;
alter table public."friendConversations" enable row level security;
alter table public."friendMessage" enable row level security;
alter table public.notifications enable row level security;

drop policy if exists "users manage own profile" on public."userProfiles";
create policy "users manage own profile"
on public."userProfiles"
for all
using (auth.uid() = "id")
with check (auth.uid() = "id");

drop policy if exists "users manage own preferences" on public."workoutPref";
create policy "users manage own preferences"
on public."workoutPref"
for all
using (auth.uid() = "userID")
with check (auth.uid() = "userID");

drop policy if exists "authenticated users can read programs" on public."programs";
create policy "authenticated users can read programs"
on public."programs"
for select
using (auth.role() = 'authenticated');

drop policy if exists "users manage own programs" on public."userPrograms";
create policy "users manage own programs"
on public."userPrograms"
for all
using (auth.uid() = "userID")
with check (auth.uid() = "userID");

drop policy if exists "users manage own workout sessions" on public."workoutSessions";
create policy "users manage own workout sessions"
on public."workoutSessions"
for all
using (auth.uid() = "userID")
with check (auth.uid() = "userID");

drop policy if exists "authenticated users can read community posts" on public."communityPosts";
create policy "authenticated users can read community posts"
on public."communityPosts"
for select
using (auth.role() = 'authenticated');

drop policy if exists "users can create community posts" on public."communityPosts";
create policy "users can create community posts"
on public."communityPosts"
for insert
with check (auth.uid() = "userID");

drop policy if exists "users read and create replies" on public."communityPostReplies";
create policy "users read and create replies"
on public."communityPostReplies"
for all
using (auth.role() = 'authenticated')
with check (auth.role() = 'authenticated');

drop policy if exists "authenticated users can read community challenges" on public."communityChallenges";
create policy "authenticated users can read community challenges"
on public."communityChallenges"
for select
using (auth.role() = 'authenticated');

drop policy if exists "users manage own friends" on public."userFriends";
create policy "users manage own friends"
on public."userFriends"
for all
using (auth.uid() = "userID")
with check (auth.uid() = "userID");

drop policy if exists "users manage own conversations" on public."friendConversations";
create policy "users manage own conversations"
on public."friendConversations"
for all
using (auth.uid() = "userOne" or auth.uid() = "userTwo")
with check (auth.uid() = "userOne" or auth.uid() = "userTwo");

drop policy if exists "users manage own messages" on public."friendMessage";
create policy "users manage own messages"
on public."friendMessage"
for all
using (exists (
  select 1 from public."friendConversations" fc
  where fc."id" = "conversationID"
    and (fc."userOne" = auth.uid() or fc."userTwo" = auth.uid())
))
with check (exists (
  select 1 from public."friendConversations" fc
  where fc."id" = "conversationID"
    and (fc."userOne" = auth.uid() or fc."userTwo" = auth.uid())
));

drop policy if exists "users manage own notifications" on public.notifications;
create policy "users manage own notifications"
on public.notifications
for all
using (auth.uid() = "userID")
with check (auth.uid() = "userID");
insert into public."programs" ("slug", "name", "description", "focus", "difficulty", "durationWeeks", "sessionsPerWeek", "coachNote", "isActive")
values
  ('strength-foundation', 'Strength Foundation', 'A four-week base plan for rebuilding lifting rhythm, movement quality, and weekly structure.', 'Strength', 'Intermediate', 4, 4, 'Use this when you want a repeatable training week with enough room for recovery.', true),
  ('mobility-reset', 'Mobility Reset', 'Short guided sessions that improve range, core control, and joint prep before harder work.', 'Mobility', 'Beginner', 3, 5, 'Best for returning from inconsistency or long seated workdays.', true),
  ('conditioning-builder', 'Conditioning Builder', 'Progressive intervals and full-body circuits for raising work capacity without losing structure.', 'Conditioning', 'Advanced', 6, 3, 'Works well beside a primary strength block when recovery is steady.', false)
on conflict ("name") do update
set
  "slug" = excluded."slug",
  "description" = excluded."description",
  "focus" = excluded."focus",
  "difficulty" = excluded."difficulty",
  "durationWeeks" = excluded."durationWeeks",
  "sessionsPerWeek" = excluded."sessionsPerWeek",
  "coachNote" = excluded."coachNote",
  "isActive" = excluded."isActive";

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public."userProfiles" ("id", "userName", "displayName", "primaryGoal", "weeklyGoal", "focus", "expLevel", "city", "bio", "email")
select
  id,
  'alex_carter',
  'Alex Carter',
  'Build a stronger weekly routine with better movement quality and clearer recovery decisions.',
  4,
  'Strength',
  'Intermediate',
  'Remote',
  'Working toward a repeatable training cadence that balances lifting, mobility, and recovery.',
  coalesce(email, concat(id::text, '@example.invalid'))
from target_user
on conflict ("id") do update
set
  "userName" = excluded."userName",
  "displayName" = excluded."displayName",
  "primaryGoal" = excluded."primaryGoal",
  "weeklyGoal" = excluded."weeklyGoal",
  "focus" = excluded."focus",
  "expLevel" = excluded."expLevel",
  "city" = excluded."city",
  "bio" = excluded."bio",
  "email" = excluded."email";

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public."workoutPref" ("userID", "camEnabled", "audioEnabled", "timePref", "recoveryDay")
select id, true, false, 'Evenings', 'Sunday'
from target_user
on conflict ("userID") do update
set
  "camEnabled" = excluded."camEnabled",
  "audioEnabled" = excluded."audioEnabled",
  "timePref" = excluded."timePref",
  "recoveryDay" = excluded."recoveryDay";

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
), selected_programs as (
  select "id", "name", "focus"
  from public."programs"
  where "name" in ('Strength Foundation', 'Mobility Reset')
)
insert into public."userPrograms" ("userID", "programID", "title", "focus", "status", "progressPercent", "nextSession", "streakDays", "completedSessions", "weeklyTarget", "weeklyCompleted")
select
  target_user.id,
  selected_programs."id",
  selected_programs."name",
  selected_programs."focus",
  case when selected_programs."focus" = 'Strength' then 'On track' else 'Recovery week' end,
  case when selected_programs."focus" = 'Strength' then 68 else 42 end,
  timezone('utc', now()) + case when selected_programs."focus" = 'Strength' then interval '1 day' else interval '2 day' end,
  case when selected_programs."focus" = 'Strength' then 4 else 2 end,
  case when selected_programs."focus" = 'Strength' then 11 else 6 end,
  case when selected_programs."focus" = 'Strength' then 4 else 5 end,
  case when selected_programs."focus" = 'Strength' then 3 else 2 end
from target_user
cross join selected_programs
on conflict do nothing;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public."workoutSessions" ("userID", "name", "focus", "durationMin", "effort", "score", "userNotes", "createdAt")
select id, 'Mobility + Core Reset', 'Mobility', 28, 'Moderate', 92, 'Camera alignment stayed stable after the first three minutes.', timezone('utc', now()) - interval '1 day' from target_user
union all
select id, 'Upper Push Strength', 'Strength', 44, 'High', 88, 'Good cadence, but shoulder position drifted during the last set.', timezone('utc', now()) - interval '3 day' from target_user
union all
select id, 'Tempo Conditioning Ladder', 'Conditioning', 35, 'High', 85, 'Strong finish and consistent breathing on later rounds.', timezone('utc', now()) - interval '5 day' from target_user
on conflict do nothing;

insert into public."communityChallenges" ("title", "description", "cadence", "participants", "startsOnDate", "endOfDate")
values
  ('7-Day Consistency Sprint', 'Complete one focused session each day, even if it is only fifteen minutes.', 'Daily', 184, current_date, current_date + 6),
  ('Posture Reset Week', 'Stack mobility, breathing, and camera-assisted alignment checks into a single recovery block.', '5 sessions', 92, current_date + 7, current_date + 13)
on conflict do nothing;

insert into public."communityPosts" ("displayName", "category", "title", "excerpt", "replyCount", "likeCount", "isPinned")
values
  ('Nina R.', 'Form check', 'What cues help you keep your rib cage stacked during overhead work?', 'I keep losing position in the second half of a set and want one cue that keeps me organized without overthinking it.', 14, 29, true),
  ('Miles T.', 'Challenge log', 'Day 12 of the morning mobility streak', 'Ten minutes has been enough to keep the habit intact, and the app cues are making the start feel easier.', 8, 21, false),
  ('Avery K.', 'Programs', 'How are people combining conditioning with Strength Foundation?', 'I want to keep two conditioning sessions each week without flattening recovery on the main lifting days.', 11, 17, false)
on conflict do nothing;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public."userFriends" ("userID", "friendName", "status", "sharedStreak", "lastWorkoutAt", "focus")
select id, 'Jordan P.', 'accepted', 5, timezone('utc', now()) - interval '1 day', 'Strength' from target_user
union all
select id, 'Camila S.', 'accepted', 3, timezone('utc', now()) - interval '2 day', 'Mobility' from target_user
union all
select id, 'Theo M.', 'pending', 0, timezone('utc', now()) - interval '4 day', 'Conditioning' from target_user
on conflict do nothing;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public.notifications ("userID", "title", "message", "category", "label", "link", "isRead", "createdAt")
select id, 'Tonight''s session is ready', 'Your next Strength Foundation workout is queued with a shoulder prep warm-up.', 'Workout', 'Open workout', '/workouts', false, timezone('utc', now()) - interval '4 hour' from target_user
union all
select id, 'Jordan matched your streak', 'Your accountability circle is still tied at five days. One session breaks the tie.', 'Friends', 'View friends', '/friends', false, timezone('utc', now()) - interval '1 day' from target_user
union all
select id, 'Challenge reminder', 'The 7-Day Consistency Sprint closes in four days. You have completed two of seven check-ins.', 'Community', 'Open community', '/community', true, timezone('utc', now()) - interval '2 day' from target_user
on conflict do nothing;
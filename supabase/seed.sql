insert into public.program_catalog (title, slug, summary, focus_area, difficulty, duration_weeks, sessions_per_week, coach_note, featured)
values
  ('Strength Foundation', 'strength-foundation', 'A four-week base plan for rebuilding lifting rhythm, movement quality, and weekly structure.', 'Strength', 'Intermediate', 4, 4, 'Use this when you want a repeatable training week with enough room for recovery.', true),
  ('Mobility Reset', 'mobility-reset', 'Short guided sessions that improve range, core control, and joint prep before harder work.', 'Mobility', 'Beginner', 3, 5, 'Best for returning from inconsistency or long seated workdays.', true),
  ('Conditioning Builder', 'conditioning-builder', 'Progressive intervals and full-body circuits for raising work capacity without losing structure.', 'Conditioning', 'Advanced', 6, 3, 'Works well beside a primary strength block when recovery is steady.', false)
on conflict (slug) do update
set
  summary = excluded.summary,
  focus_area = excluded.focus_area,
  difficulty = excluded.difficulty,
  duration_weeks = excluded.duration_weeks,
  sessions_per_week = excluded.sessions_per_week,
  coach_note = excluded.coach_note,
  featured = excluded.featured;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public.user_profiles (user_id, display_name, training_goal, weekly_goal, focus_area, level, city, bio)
select
  id,
  'Alex Carter',
  'Build a stronger weekly routine with better movement quality and clearer recovery decisions.',
  4,
  'Strength',
  'Intermediate',
  'Remote',
  'Working toward a repeatable training cadence that balances lifting, mobility, and recovery.'
from target_user
on conflict (user_id) do update
set
  display_name = excluded.display_name,
  training_goal = excluded.training_goal,
  weekly_goal = excluded.weekly_goal,
  focus_area = excluded.focus_area,
  level = excluded.level,
  city = excluded.city,
  bio = excluded.bio;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public.training_preferences (user_id, camera_enabled, audio_cues, preferred_time, recovery_day)
select id, true, false, 'Evenings', 'Sunday'
from target_user
on conflict (user_id) do update
set
  camera_enabled = excluded.camera_enabled,
  audio_cues = excluded.audio_cues,
  preferred_time = excluded.preferred_time,
  recovery_day = excluded.recovery_day;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
), selected_programs as (
  select id, title, focus_area
  from public.program_catalog
  where slug in ('strength-foundation', 'mobility-reset')
)
insert into public.user_programs (user_id, program_id, title, focus_area, status, progress_percent, next_session, streak_days, completed_sessions, weekly_target, weekly_completed)
select
  target_user.id,
  selected_programs.id,
  selected_programs.title,
  selected_programs.focus_area,
  case when selected_programs.focus_area = 'Strength' then 'On track' else 'Recovery week' end,
  case when selected_programs.focus_area = 'Strength' then 68 else 42 end,
  timezone('utc', now()) + case when selected_programs.focus_area = 'Strength' then interval '1 day' else interval '2 day' end,
  case when selected_programs.focus_area = 'Strength' then 4 else 2 end,
  case when selected_programs.focus_area = 'Strength' then 11 else 6 end,
  case when selected_programs.focus_area = 'Strength' then 4 else 5 end,
  case when selected_programs.focus_area = 'Strength' then 3 else 2 end
from target_user
cross join selected_programs
on conflict do nothing;

with target_user as (
  select id
  from auth.users
  order by created_at asc
  limit 1
)
insert into public.workout_sessions (user_id, title, focus_area, duration_minutes, effort, score, notes, completed_at)
select id, 'Mobility + Core Reset', 'Mobility', 28, 'Moderate', 92, 'Camera alignment stayed stable after the first three minutes.', timezone('utc', now()) - interval '1 day' from target_user
union all
select id, 'Upper Push Strength', 'Strength', 44, 'High', 88, 'Good cadence, but shoulder position drifted during the last set.', timezone('utc', now()) - interval '3 day' from target_user
union all
select id, 'Tempo Conditioning Ladder', 'Conditioning', 35, 'High', 85, 'Strong finish and consistent breathing on later rounds.', timezone('utc', now()) - interval '5 day' from target_user
on conflict do nothing;

insert into public.community_challenges (title, description, cadence, participants, starts_on, ends_on)
values
  ('7-Day Consistency Sprint', 'Complete one focused session each day, even if it is only fifteen minutes.', 'Daily', 184, current_date, current_date + 6),
  ('Posture Reset Week', 'Stack mobility, breathing, and camera-assisted alignment checks into a single recovery block.', '5 sessions', 92, current_date + 7, current_date + 13)
on conflict do nothing;

insert into public.community_posts (author_name, category, title, excerpt, reply_count, like_count, is_pinned)
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
insert into public.friendships (user_id, friend_name, status, shared_streak, last_workout_at, focus_area)
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
insert into public.notifications (user_id, title, message, category, cta_label, cta_href, is_read, created_at)
select id, 'Tonight''s session is ready', 'Your next Strength Foundation workout is queued with a shoulder prep warm-up.', 'Workout', 'Open workout', '/workouts', false, timezone('utc', now()) - interval '4 hour' from target_user
union all
select id, 'Jordan matched your streak', 'Your accountability circle is still tied at five days. One session breaks the tie.', 'Friends', 'View friends', '/friends', false, timezone('utc', now()) - interval '1 day' from target_user
union all
select id, 'Challenge reminder', 'The 7-Day Consistency Sprint closes in four days. You have completed two of seven check-ins.', 'Community', 'Open community', '/community', true, timezone('utc', now()) - interval '2 day' from target_user
on conflict do nothing;
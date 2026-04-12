import { Flame, HeartHandshake, UserPlus2, Users } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  InlineLink,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { formatLongDate, getFriendsData } from "@/lib/site-data";
import { Suspense } from "react";

function FriendsPageFallback() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Friends"
        title="Keep your accountability circle visible, current, and easy to act on."
        description="Loading friendships, pending invites, and shared streaks."
      />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Accepted" value="--" detail="Loading active friendships." icon={Users} />
        <StatCard label="Pending" value="--" detail="Loading pending invites." icon={UserPlus2} />
        <StatCard label="Top shared streak" value="--" detail="Loading shared streak data." icon={Flame} />
        <StatCard label="Support mode" value="Loading" detail="Preparing accountability activity." icon={HeartHandshake} />
      </section>
    </AppPage>
  );
}

async function FriendsPageContent() {
  const friendships = await getFriendsData();
  const accepted = friendships.data.filter((friend) => friend.status === "accepted");
  const pending = friendships.data.filter((friend) => friend.status !== "accepted");
  const longestSharedStreak = accepted.length ? Math.max(...accepted.map((friend) => friend.shared_streak)) : 0;

  return (
    <AppPage>
      <PageHero
        eyebrow="Friends"
        title="Keep your accountability circle visible, current, and easy to act on."
        description="Follow active connections, pending invites, and shared streaks from one place."
        actions={[
          { href: "/community", label: "Open community", secondary: true },
          { href: "/workouts", label: "Train now" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={friendships.source}
              viewerState={friendships.viewerState}
              viewerEmail={friendships.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-slate-950 px-5 py-5 text-white">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-white/55">Circle health</div>
              <div className="mt-4 text-4xl font-semibold tracking-[-0.04em]">{accepted.length}</div>
              <p className="mt-2 text-sm leading-6 text-white/70">Current active connections shown in your circle.</p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Accepted" value={String(accepted.length).padStart(2, "0")} detail="Connections already active in your training circle." icon={Users} />
        <StatCard label="Pending" value={String(pending.length).padStart(2, "0")} detail="Connections waiting for a response or confirmation." icon={UserPlus2} />
        <StatCard label="Top shared streak" value={`${longestSharedStreak} days`} detail="The strongest current run with someone in your circle." icon={Flame} />
        <StatCard label="Support mode" value="Active" detail="Recent activity and follow-ups stay easy to scan here." icon={HeartHandshake} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <SectionCard
          eyebrow="Accountability circle"
          title="People moving with you right now"
          description="Accepted connections are shown with recency and shared training themes so the page stays useful at a glance."
        >
          <div className="space-y-4">
            {accepted.length ? (
              accepted.map((friend) => (
                <article key={friend.id} className="rounded-[26px] border border-black/10 bg-white/72 px-5 py-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="text-2xl font-semibold tracking-[-0.03em] text-foreground">{friend.friend_name}</div>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        Focused on {friend.focus_area.toLowerCase()} and last active {formatLongDate(friend.last_workout_at)}.
                      </p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 lg:min-w-[260px]">
                      <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Shared streak</div>
                        <div className="mt-2 text-lg font-semibold text-foreground">{friend.shared_streak} days</div>
                      </div>
                      <div className="rounded-2xl border border-black/10 bg-background/60 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Status</div>
                        <div className="mt-2 text-lg font-semibold capitalize text-foreground">{friend.status}</div>
                      </div>
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <div className="rounded-[24px] border border-dashed border-black/10 bg-background/60 px-5 py-5 text-sm leading-6 text-muted-foreground">
                Your accountability circle will appear here once friendships have been created.
              </div>
            )}
          </div>
        </SectionCard>

        <div className="grid gap-6">
          <SectionCard
            eyebrow="Pending requests"
            title="Follow-ups"
            description="Keep unanswered invites visible so they do not disappear into the background."
          >
            <div className="space-y-3">
              {pending.length ? (
                pending.map((friend) => (
                  <div key={friend.id} className="rounded-[22px] border border-black/10 bg-white/70 px-4 py-4">
                    <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">{friend.friend_name}</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">Status: {friend.status}. Shared focus: {friend.focus_area}.</p>
                  </div>
                ))
              ) : (
                <div className="rounded-[22px] border border-dashed border-black/10 bg-background/60 px-4 py-4 text-sm leading-6 text-muted-foreground">
                  No pending invites right now.
                </div>
              )}
            </div>
            <div className="mt-5">
              <InlineLink href="/community">Find more accountability through challenges</InlineLink>
            </div>
          </SectionCard>
        </div>
      </section>
    </AppPage>
  );
}

export default function FriendsPage() {
  return (
    <Suspense fallback={<FriendsPageFallback />}>
      <FriendsPageContent />
    </Suspense>
  );
}

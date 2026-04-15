import { Flag, MessageSquareMore, Trophy, Users2 } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  InlineLink,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { formatShortDate, getCommunityData } from "@/lib/site-data";
import { Suspense } from "react";

function CommunityPageFallback() {
  return (
    <AppPage>
      <PageHero
        eyebrow="Community hub"
        title="Bring challenges, discussion, and accountability into the same training loop."
        description="Loading community activity, challenges, and discussion previews."
      />
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Open challenges" value="--" detail="Loading current community challenges." icon={Trophy} />
        <StatCard label="Recent discussions" value="--" detail="Loading recent conversation activity." icon={MessageSquareMore} />
        <StatCard label="Pinned topics" value="--" detail="Loading pinned discussion threads." icon={Flag} />
        <StatCard label="Participation" value="--" detail="Loading community participation totals." icon={Users2} />
      </section>
    </AppPage>
  );
}

async function CommunityPageContent() {
  const community = await getCommunityData();
  const pinnedCount = community.data.posts.filter((post) => post.isPinned).length;

  return (
    <AppPage>
      <PageHero
        eyebrow="Community hub"
        title="Bring challenges, discussion, and accountability into the same training loop."
        description="Challenges, discussion, and check-ins stay organized here so the community side of training is easy to follow."
        actions={[
          { href: "/friends", label: "View friends", secondary: true },
          { href: "/workouts", label: "Start a session" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={community.source}
              viewerState={community.viewerState}
              viewerEmail={community.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-white/75 px-5 py-5">
              {/* Internal note: keep this panel descriptive, not editorial. */}
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Community activity</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                Active challenges and recent conversations help keep the training community visible throughout the week.
              </p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Open challenges" value={String(community.data.challenges.length).padStart(2, "0")} detail="Short accountability cycles that are easy to join mid-week." icon={Trophy} />
        <StatCard label="Recent discussions" value={String(community.data.posts.length).padStart(2, "0")} detail="Focused posts instead of an unstructured wall of noise." icon={MessageSquareMore} />
        <StatCard label="Pinned topics" value={String(pinnedCount).padStart(2, "0")} detail="High-value prompts that deserve to stay visible longer." icon={Flag} />
        <StatCard label="Participation" value={`${community.data.challenges.reduce((sum, challenge) => sum + challenge.participants, 0)}`} detail="Active challenge enrollment across the latest community events." icon={Users2} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <SectionCard
          eyebrow="Challenges"
          title="Current and upcoming accountability blocks"
          description="Challenges are framed as short commitments with visible participation and dates."
        >
          <div className="space-y-4">
            {community.data.challenges.length ? (
              community.data.challenges.map((challenge) => (
                <article key={challenge.id} className="rounded-[24px] border border-black/10 bg-white/72 px-5 py-5">
                  <div className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-primary w-fit">
                    {challenge.cadence}
                  </div>
                  <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{challenge.title}</h2>
                  <p className="mt-3 text-sm leading-7 text-muted-foreground">{challenge.description}</p>
                  <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium text-muted-foreground">
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{challenge.participants} participants</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{formatShortDate(challenge.startsOnDate)} to {formatShortDate(challenge.endOfDate)}</span>
                  </div>
                </article>
              ))
            ) : (
              <div className="rounded-[24px] border border-dashed border-black/10 bg-background/60 px-5 py-5 text-sm leading-6 text-muted-foreground">
                Challenge records will appear here once the community tables are populated.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Discussion"
          title="Conversations worth opening"
          description="Pinned posts and recent replies are arranged like a real forum shortlist instead of a placeholder paragraph."
        >
          <div className="space-y-4">
            {community.data.posts.length ? (
              community.data.posts.map((post) => (
                <article key={post.id} className="rounded-[26px] border border-black/10 bg-white/72 px-5 py-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-accent-foreground">
                      {post.category}
                    </span>
                    {post.isPinned ? (
                      <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
                        Pinned
                      </span>
                    ) : null}
                  </div>
                  <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{post.title}</h2>
                  <p className="mt-3 text-sm leading-7 text-muted-foreground">{post.excerpt}</p>
                  <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium text-muted-foreground">
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{post.displayName}</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{post.replyCount} replies</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{post.likeCount} likes</span>
                    <span className="rounded-full border border-black/10 bg-background/70 px-3 py-1">{formatShortDate(post.createdAt)}</span>
                  </div>
                </article>
              ))
            ) : (
              <div className="rounded-[24px] border border-dashed border-black/10 bg-background/60 px-5 py-5 text-sm leading-6 text-muted-foreground">
                Community posts will render here after the first forum topics are created.
              </div>
            )}
          </div>
          <div className="mt-6">
            <InlineLink href="/friends">Continue the accountability loop with friends</InlineLink>
          </div>
        </SectionCard>
      </section>
    </AppPage>
  );
}

export default function CommunityPage() {
  return (
    <Suspense fallback={<CommunityPageFallback />}>
      <CommunityPageContent />
    </Suspense>
  );
}

import { BellRing, CheckCheck, Layers3, Zap } from "lucide-react";

import {
  AppPage,
  DataSourceNotice,
  PageHero,
  SectionCard,
  StatCard,
} from "@/components/app/page-primitives";
import { NotificationsInbox } from "@/components/app/notifications-inbox";
import { getNotificationsData } from "@/lib/site-data";

export default async function NotificationsPage() {
  const notifications = await getNotificationsData();
  const unread = notifications.data.filter((notification) => !notification.is_read);

  return (
    <AppPage>
      <PageHero
        eyebrow="Notifications"
        title="Make alerts useful by keeping them tied to the next action."
        description="Notifications should tell you what changed, why it matters, and where to go next. This page turns alerts into a focused activity inbox instead of a dead-end list."
        actions={[
          { href: "/programs", label: "View programs", secondary: true },
          { href: "/workouts", label: "Open workout" },
        ]}
        aside={
          <>
            <DataSourceNotice source={notifications.source} tables={["notifications"]} />
            <div className="rounded-[26px] border border-black/10 bg-white/75 px-5 py-5">
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Inbox guidance</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                Keep unread items short and actionable. Everything else should age into background context quickly.
              </p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Unread" value={String(unread.length).padStart(2, "0")} detail="Items that still need attention or a click-through." icon={BellRing} />
        <StatCard label="Activity items" value={String(notifications.data.length).padStart(2, "0")} detail="Recent messages coming from workouts, community, and friends." icon={Layers3} />
        <StatCard label="Read rate" value={`${notifications.data.length ? Math.round(((notifications.data.length - unread.length) / notifications.data.length) * 100) : 0}%`} detail="A quick signal of whether the inbox feels manageable." icon={CheckCheck} />
        <StatCard label="Priority" value="Focused" detail="The page is organized around direct actions, not passive badges." icon={Zap} />
      </section>

      <SectionCard
        eyebrow="Activity inbox"
        title="Recent alerts"
        description="Notifications are grouped into clean cards with optional deep links into the relevant page."
      >
        <NotificationsInbox notifications={notifications.data} />
      </SectionCard>
    </AppPage>
  );
}

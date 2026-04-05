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
        description="Notifications keep recent activity, reminders, and updates close to the next action."
        actions={[
          { href: "/programs", label: "View programs", secondary: true },
          { href: "/workouts", label: "Open workout" },
        ]}
        aside={
          <>
            <DataSourceNotice
              source={notifications.source}
              viewerState={notifications.viewerState}
              viewerEmail={notifications.viewerEmail}
            />
            <div className="rounded-[26px] border border-black/10 bg-white/75 px-5 py-5">
              {/* Internal note: this block should read like product copy, not operator guidance. */}
              <div className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">Inbox overview</div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                Unread items, workout reminders, and community updates stay collected here in one place.
              </p>
            </div>
          </>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Unread" value={String(unread.length).padStart(2, "0")} detail="Items that still need attention or a click-through." icon={BellRing} />
        <StatCard label="Activity items" value={String(notifications.data.length).padStart(2, "0")} detail="Recent messages coming from workouts, community, and friends." icon={Layers3} />
        <StatCard label="Read rate" value={`${notifications.data.length ? Math.round(((notifications.data.length - unread.length) / notifications.data.length) * 100) : 0}%`} detail="A snapshot of how much recent activity has already been cleared." icon={CheckCheck} />
        <StatCard label="Priority" value="Focused" detail="The latest updates stay close to the actions they belong to." icon={Zap} />
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

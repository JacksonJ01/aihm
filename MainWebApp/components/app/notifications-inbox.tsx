import Link from "next/link";

import { markAllNotificationsReadAction, markNotificationReadAction } from "@/app/notifications/actions";
import type { Notifications } from "@/lib/site-data";
import { formatLongDate } from "@/lib/site-data";
import { getSafeAppPath } from "@/lib/utils";

type NotificationsInboxProps = {
  notifications: Notifications[];
};

export function NotificationsInbox({ notifications }: NotificationsInboxProps) {
  const unreadCount = notifications.filter((notification) => !notification.isRead).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-[26px] border border-black/10 bg-white/72 px-5 py-5 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Inbox actions</div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Use the controls below to clear low-friction alerts quickly and keep the page focused on what still needs attention.
          </p>
        </div>
        <form action={markAllNotificationsReadAction}>
          <button type="submit" className="button-secondary" disabled={unreadCount === 0}>
            Mark all as read
          </button>
        </form>
      </div>

      {notifications.length ? (
        notifications.map((notification) => {
          const safeHref = getSafeAppPath(notification.link);

          return (
          <article key={notification.id} className="rounded-[26px] border border-black/10 bg-white/72 px-5 py-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-2xl">
                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full bg-accent px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-accent-foreground">
                    {notification.category}
                  </span>
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${notification.isRead ? "border border-black/10 bg-background/70 text-muted-foreground" : "bg-primary/10 text-primary"}`}>
                    {notification.isRead ? "Read" : "Unread"}
                  </span>
                </div>
                <h2 className="mt-4 text-2xl font-semibold tracking-[-0.03em] text-foreground">{notification.title}</h2>
                <p className="mt-3 text-sm leading-7 text-muted-foreground">{notification.message}</p>
              </div>

              <div className="flex min-w-[200px] flex-col items-start gap-3 lg:items-end">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {formatLongDate(notification.createdAt)}
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  {safeHref && notification.label ? (
                    <Link href={safeHref} className="button-secondary">
                      {notification.label}
                    </Link>
                  ) : null}
                  {!notification.isRead ? (
                    <form action={markNotificationReadAction}>
                      <input type="hidden" name="notification_id" value={notification.id} />
                      <button type="submit" className="button-primary">
                        Mark read
                      </button>
                    </form>
                  ) : null}
                </div>
              </div>
            </div>
          </article>
        );
        })
      ) : (
        <div className="rounded-[24px] border border-dashed border-black/10 bg-background/60 px-5 py-5 text-sm leading-6 text-muted-foreground">
          Notifications will populate here as workouts, community events, and friend activity generate updates.
        </div>
      )}
    </div>
  );
}
"use client";

import { JOINT_ANGLE_DEFINITIONS, type JointAngles } from "@/lib/pose";

type Props = {
  jointAngles: JointAngles;
  trackerReady: boolean;
  poseDetected: boolean;
  isCameraOn: boolean;
  side?: "left" | "right" | "all";
  className?: string;
};

function formatAngle(angle: number | null) {
  return angle === null ? "--" : `${angle}°`;
}

function AngleRow({ label, angle }: { label: string; angle: number | null }) {
  return (
    <div className="rounded-xl border border-black/10 bg-white/70 px-3 py-2.5 shadow-[0_10px_22px_rgba(29,35,43,0.05)]">
      <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-base font-semibold tracking-[-0.03em] text-foreground sm:text-[0.95rem]">{formatAngle(angle)}</div>
    </div>
  );
}

export default function PoseEstimation({ jointAngles, trackerReady, poseDetected, isCameraOn, side = "all", className }: Props) {
  const statusLabel = !trackerReady
    ? "Loading tracker"
    : isCameraOn
      ? poseDetected
        ? "Tracking active"
        : "Camera live, finding pose"
      : "Tracker ready";

  const visibleDefinitions = JOINT_ANGLE_DEFINITIONS.filter((definition) => {
    if (side === "left") {
      return definition.key.startsWith("left");
    }

    if (side === "right") {
      return definition.key.startsWith("right");
    }

    return true;
  });

  const titleLabel = side === "left" ? "Left-side joint angles" : side === "right" ? "Right-side joint angles" : "Joint angles";
  const subtitleLabel = side === "left" ? "Left body chain" : side === "right" ? "Right body chain" : "Live 3D body metrics";

  return (
    <aside className={`flex h-full min-h-[420px] w-full flex-col overflow-hidden rounded-[28px] border border-black/10 bg-white/80 px-3 py-3 shadow-[0_18px_40px_rgba(29,35,43,0.08)] sm:px-4 sm:py-4 ${className ?? ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{titleLabel}</div>
          <h3 className="mt-1 text-sm font-semibold tracking-[-0.03em] text-foreground sm:text-[0.95rem]">{subtitleLabel}</h3>
        </div>
        <div className="shrink-0 rounded-full border border-black/10 bg-slate-950 px-2.5 py-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-white sm:text-[10px]">
          {statusLabel}
        </div>
      </div>

      <div className="mt-3 flex flex-1 flex-col gap-2">
        {visibleDefinitions.map((definition) => (
          <AngleRow key={definition.key} label={definition.label} angle={jointAngles[definition.key]} />
        ))}
      </div>

      <div className="mt-3 rounded-xl border border-dashed border-black/10 bg-background/60 px-3 py-2 text-[11px] leading-5 text-muted-foreground sm:text-xs">
        Tracked joints: shoulders, elbows, hips, and knees.
      </div>
    </aside>
  );
}

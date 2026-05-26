"use client";

import { motion } from "framer-motion";

import { avatarUrl, displayName, initialsOf } from "@/lib/avatars";

import { cn } from "@/lib/utils";

interface AvatarCircleProps {
  slug: string | null;
  size?: number;
  ringed?: boolean;
  className?: string;
  /** When true, scales the entrance for the empty-state "hero" use:
   * 360→full reveal with a spring. When false (toolbar use), instant. */
  animate?: boolean;
}

/**
 * Round avatar for a consultant. Tries to render their /avatars/<First>.png
 * via the slug→url map in lib/avatars.ts. Falls back to initials in a
 * brand-cyan circle when no PNG exists — covers future consultants
 * before someone drops their photo in.
 *
 * `ringed` adds a soft cyan halo, used in the empty-state hero.
 */
export function AvatarCircle({
  slug,
  size = 112,
  ringed = false,
  className,
  animate = true,
}: AvatarCircleProps) {
  const src = avatarUrl(slug);
  const initials = initialsOf(slug);
  const dim = { width: size, height: size } as const;

  const inner = src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={displayName(slug)}
      style={dim}
      className="h-full w-full rounded-full object-cover"
    />
  ) : (
    <div
      style={dim}
      className="flex h-full w-full items-center justify-center rounded-full bg-primary text-primary-foreground"
    >
      <span
        className="font-semibold"
        style={{ fontSize: Math.round(size * 0.36) }}
      >
        {initials}
      </span>
    </div>
  );

  const wrap = cn(
    "relative inline-flex shrink-0 items-center justify-center rounded-full",
    // Ring + soft glow for the hero placement.
    ringed && "ring-4 ring-primary/15",
    ringed && "shadow-[0_0_0_8px_hsl(var(--accent))]",
    className,
  );

  if (!animate) {
    return (
      <div className={wrap} style={dim}>
        {inner}
      </div>
    );
  }
  return (
    <motion.div
      // layoutId lets AnimatePresence track this avatar across consultant
      // switches so the swap animates as a single morph rather than a
      // hard mount/unmount.
      layoutId="agent-avatar"
      className={wrap}
      style={dim}
      initial={{ opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.82 }}
      transition={{ type: "spring", stiffness: 240, damping: 22 }}
    >
      {inner}
    </motion.div>
  );
}

"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Renders the confirm button in destructive red + uses a red alert icon.
   *  Use for any delete / wipe / revert action. */
  destructive?: boolean;
  /** Spinner on the confirm button + locks out the cancel/backdrop while
   *  the action is in flight, so a double-click doesn't fire twice. */
  busy?: boolean;
}

/**
 * Replacement for window.confirm() — Harcourts-branded, animated, and
 * scoped to the chat shell. Same shape as HUP-Sales-App's existing
 * confirmation-modal.tsx so it reads as one product. Lives here (not
 * in lib/) so the standalone repo's chat at localhost:3010 has the
 * same component without depending on the HUP repo.
 *
 * Renders nothing when closed (AnimatePresence handles exit anim).
 * Esc key closes; backdrop click closes; both gated on !busy so the
 * user can't accidentally bail mid-delete.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
}: ConfirmDialogProps) {
  // Esc-to-close. Listener only attached while open + not busy.
  useEffect(() => {
    if (!open || busy) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  // SSR-safe mount flag — createPortal needs document.body, which only
  // exists in the browser. Before hydration we render nothing; after,
  // we portal to body so the dialog ALWAYS centers in the viewport
  // regardless of any overflow:hidden parent (the chat shell has
  // overflow:hidden + position:absolute, which clipped the dialog's
  // top when it was rendered in-tree).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  const overlay = (
    <AnimatePresence>
      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
        >
          {/* Backdrop — darker than the previous /40 so the dialog
              reads as a distinct surface even against a white chat
              behind it. backdrop-blur is keep for the soft focus. */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="absolute inset-0 bg-slate-900/60 backdrop-blur-[2px]"
            onClick={busy ? undefined : onClose}
          />

          {/* Dialog panel. Uses LITERAL tailwind colors (bg-white,
              text-slate-*) rather than theme tokens. Reason: the
              dialog is portaled to document.body, which in HUP-Sales-App
              sits OUTSIDE .harcourts-chat-shell — and our shadcn-style
              tokens (--background, --foreground, --muted, --primary)
              are scoped to that shell. Outside the shell they don't
              resolve and bg-background ends up transparent. Hardcoded
              slate/white avoids that whole class of bug. */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            transition={{ duration: 0.2, ease: [0.33, 1, 0.68, 1] }}
            className="relative w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10"
          >
            <div className="p-6">
              <div className="flex items-start gap-4">
                <div
                  className={cn(
                    "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl",
                    destructive ? "bg-red-50" : "bg-amber-50",
                  )}
                >
                  <AlertTriangle
                    className={cn(
                      "h-5 w-5",
                      destructive ? "text-red-600" : "text-amber-600",
                    )}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <h3
                    id="confirm-dialog-title"
                    className="text-base font-semibold text-slate-900"
                  >
                    {title}
                  </h3>
                  {/* whitespace-pre-line lets the caller include `\n` for
                      paragraph breaks without HTML markup. */}
                  <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-600">
                    {description}
                  </p>
                </div>
              </div>

              <div className="mt-7 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={busy}
                  className="rounded-xl px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50"
                >
                  {cancelLabel}
                </button>
                <button
                  type="button"
                  onClick={onConfirm}
                  disabled={busy}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-xl px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-slate-900/10",
                    "transition-all active:scale-[0.98]",
                    "disabled:cursor-not-allowed disabled:opacity-70",
                    destructive
                      ? "bg-red-600 hover:bg-red-700"
                      : "bg-[#00ADEF] hover:bg-[#0095CE]",
                  )}
                >
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  {busy ? "Working…" : confirmLabel}
                </button>
              </div>
            </div>

            {/* Close (X) — top-right. Hidden while busy so the user
                can't ditch the dialog mid-delete. */}
            {!busy && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="absolute right-3 top-3 rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );

  return createPortal(overlay, document.body);
}

"use client";

import { Check, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface SaveLearningFormProps {
  /** The user prompt that came right before this assistant turn — used to
   *  pre-fill the "trigger" field so the form is mostly already filled in. */
  defaultTrigger: string;
  onCancel: () => void;
  onSave: (args: { title: string; trigger: string; rule: string }) => Promise<void>;
}

export function SaveLearningForm({
  defaultTrigger,
  onCancel,
  onSave,
}: SaveLearningFormProps) {
  const [title, setTitle] = useState("");
  const [trigger, setTrigger] = useState(defaultTrigger);
  const [rule, setRule] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave =
    title.trim().length > 0 &&
    trigger.trim().length > 0 &&
    rule.trim().length > 0 &&
    !saving;

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        title: title.trim(),
        trigger: trigger.trim(),
        rule: rule.trim(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="mt-3 space-y-3 rounded-md border bg-background p-3"
    >
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          Title
        </label>
        <Input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Never lead with 'nestled'"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          When this came up
        </label>
        <Input
          value={trigger}
          onChange={(e) => setTrigger(e.target.value)}
          placeholder="What was being written when this rule applied?"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">
          Rule going forward
        </label>
        <textarea
          value={rule}
          onChange={(e) => setRule(e.target.value)}
          rows={3}
          placeholder="What should the consultant always do (or never do)?"
          className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={saving}
        >
          <X className="mr-1.5 h-3.5 w-3.5" />
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={!canSave}>
          <Check className="mr-1.5 h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save rule"}
        </Button>
      </div>
    </form>
  );
}

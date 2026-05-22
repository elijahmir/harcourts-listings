"use client";

import { Paperclip } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";

interface UploadButtonProps {
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}

export function UploadButton({ disabled, onFiles }: UploadButtonProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,.heic,.heif,application/pdf"
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFiles(files);
          // Reset so the same file can be picked again later.
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        aria-label="Attach photos or floor plan"
        title="Attach photos or floor plan"
      >
        <Paperclip className="h-4 w-4" />
      </Button>
    </>
  );
}

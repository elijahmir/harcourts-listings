"use client";

import { useEffect, useState } from "react";

import { Chat } from "@/components/chat";
import { NamePrompt } from "@/components/name-prompt";
import { getUserName, setUserName } from "@/lib/storage";

/**
 * Resolve the backend URL at runtime.
 *
 * Default: same host as the browser, port 3000. So opening the app on
 * the Mac at http://localhost:3010 connects to http://localhost:3000;
 * opening it on a phone at http://192.168.1.53:3010 connects to
 * http://192.168.1.53:3000. No env var needed.
 *
 * Override via NEXT_PUBLIC_BACKEND_URL only if the backend is on a
 * different host (e.g. behind a Tailscale Funnel proxy).
 */
function resolveBackendUrl(): string {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:3000`;
  }
  return "http://127.0.0.1:3000"; // SSR fallback; never actually hit
}

export default function Home() {
  const [name, setName] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [backendUrl, setBackendUrl] = useState<string>("");

  useEffect(() => {
    setName(getUserName());
    setBackendUrl(resolveBackendUrl());
    setHydrated(true);
  }, []);

  // Avoid flashing the name prompt during SSR hydration.
  if (!hydrated) return null;

  if (!name) {
    return (
      <NamePrompt
        onSubmit={(n) => {
          setUserName(n);
          setName(n);
        }}
      />
    );
  }

  return <Chat userName={name} backendUrl={backendUrl} />;
}

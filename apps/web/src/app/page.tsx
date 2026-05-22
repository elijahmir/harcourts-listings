"use client";

import { useEffect, useState } from "react";

import { Chat } from "@/components/chat";
import { NamePrompt } from "@/components/name-prompt";
import { getUserName, setUserName } from "@/lib/storage";

/**
 * Resolve the backend URL at runtime — handles three deployment shapes.
 *
 * 1. Dev on this Mac: browser at http://localhost:3010 → backend at
 *    http://localhost:3000 (different port, frontend and backend
 *    served independently).
 * 2. LAN / tailnet direct: browser at http://my-mac.tail-xxx.ts.net:3010
 *    → backend at http://my-mac.tail-xxx.ts.net:3000. Same shape as dev.
 * 3. Production via Tailscale Funnel (or any reverse proxy): browser
 *    at https://my-mac.tail-xxx.ts.net (no explicit port). The proxy
 *    in front routes / to the frontend and /api, /healthz, /ws to the
 *    backend. From the browser's perspective everything is same-origin.
 *
 * Detection rule: if window.location has an explicit port, we're in case
 * 1 or 2, append :3000. If not, we're in case 3 (Funnel), use same-origin.
 *
 * NEXT_PUBLIC_BACKEND_URL overrides this entire derivation if set —
 * useful for unusual setups (e.g. backend on a different host).
 */
function resolveBackendUrl(): string {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    return process.env.NEXT_PUBLIC_BACKEND_URL;
  }
  if (typeof window !== "undefined") {
    const { protocol, hostname, port } = window.location;
    if (!port) {
      // Funnel / reverse proxy: same origin handles everything.
      return `${protocol}//${hostname}`;
    }
    // Dev or LAN direct: backend lives on the same host, port 3000.
    return `${protocol}//${hostname}:3000`;
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

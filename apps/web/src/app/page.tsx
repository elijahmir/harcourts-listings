"use client";

import { useEffect, useState } from "react";

import { Chat } from "@/components/chat";
import { NamePrompt } from "@/components/name-prompt";
import { getUserName, setUserName } from "@/lib/storage";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:3000";

export default function Home() {
  const [name, setName] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setName(getUserName());
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

  return <Chat userName={name} backendUrl={BACKEND_URL} />;
}

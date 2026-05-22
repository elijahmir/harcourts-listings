# Harcourts Web

Browser chat UI for the listing generator. Next.js 15 + Tailwind + shadcn-style components, talking to `services/backend/` over WebSocket.

## First-time setup

```bash
cd apps/web
npm install      # or pnpm install / yarn install
cp .env.example .env.local
```

Edit `.env.local` if your backend isn't on `http://127.0.0.1:3000`.

## Run

```bash
npm run dev
```

Opens at [http://localhost:3010](http://localhost:3010).

The backend must also be running (`services/backend/scripts/dev.sh` in another terminal).

## How it works

1. First visit → the UI asks for your name and saves it to localStorage. There is no sign-in.
2. Pick a consultant from the dropdown. The list is fetched from the backend's `/healthz` (which reads the on-disk `consultants/` folder).
3. Type a message and hit send. The UI opens a WebSocket to `/ws/chat`, posts `{type: "user_message", ...}`, and streams the assistant response back as `chunk` events. The final `done` event includes token counts and a `claude_session_id` we persist so the next turn warm-caches.
4. Switching consultants resets the `claude_session_id` (each consultant has its own conversation context).

## Production build

```bash
npm run build
npm run start
```

For the office Mac, this will be wrapped in a launchd plist together with the backend. Not done yet.

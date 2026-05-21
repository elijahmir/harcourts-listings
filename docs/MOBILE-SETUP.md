# Mobile setup — for staff

This is the only guide you need. Follow it once on each phone or laptop you want to use, then keep it bookmarked for the day-to-day flow at the end.

The system runs on the shared MacBook at the office. Your phone or laptop talks to that Mac over a private network called **Tailscale**. Nothing is on the public internet, and there's no app to log into other than Tailscale itself.

If anything below stops working, the cause is almost always Tailscale showing **Not Connected**. Check that first.

---

## What the office admin will send you

Before you start, the admin will message you two URLs, usually in WhatsApp, iMessage, or email. They look something like this:

- **Listings:** `http://harcourts-mac.tail-xxxx.ts.net:7681`
- **Photos:** `http://harcourts-mac.tail-xxxx.ts.net:8080`

The exact text after `tail-` is specific to your office. Don't worry about what it means — you just paste it.

If you also use a laptop or desktop, you'll use those same two URLs there.

---

## iPhone — one-time setup (about 10 minutes)

You do this once per iPhone. After it's done, you only need to tap two icons to start working.

### 1. Install Tailscale

1. Open the **App Store**.
2. Search for **Tailscale**.
3. Tap **Get** to install.

### 2. Sign in to Tailscale

1. Open **Tailscale**.
2. Tap **Get Started**.
3. Tap whichever sign-in option the admin tells you to use (usually **Sign in with Google**).
4. Accept the access prompt iPhone shows you. Tailscale needs permission to run as a VPN — that's normal and expected.
5. The admin will have sent an invitation. If iPhone asks you to approve it, tap **Approve**.
6. Wait until you see a green **Connected** indicator in Tailscale. Once it's green, you can leave the app. Tailscale runs in the background from now on.

### 3. Save the Listings page to your home screen

1. Open **Safari**.
2. In the address bar, paste the **Listings** URL the admin sent you. Tap go.
3. The page should load and show a chat. If it doesn't load, check Tailscale is still **Connected**.
4. Tap the **Share** icon at the bottom of the screen (the square with an arrow pointing up).
5. Scroll the menu down and tap **Add to Home Screen**.
6. The default name **Harcourts Listings** is fine. Tap **Add**.

### 4. Save the Photos page to your home screen

1. Back in Safari, paste the **Photos** URL.
2. Tap the **Share** icon → **Add to Home Screen**.
3. Name it **Harcourts Photos**. Tap **Add**.

You're done. You now have two Harcourts icons on your home screen.

---

## Android — one-time setup (about 10 minutes)

Same idea, slightly different buttons.

### 1. Install Tailscale

1. Open the **Play Store**.
2. Search for **Tailscale**.
3. Tap **Install**.

### 2. Sign in

1. Open **Tailscale**.
2. Tap **Sign in**.
3. Use whichever sign-in option the admin tells you to use.
4. Approve the **VPN connection request** Android shows.
5. Wait for the green **Connected** indicator.

### 3. Save Listings to your home screen

1. Open **Chrome**.
2. Paste the **Listings** URL in the address bar. Tap go.
3. Tap the three dots ⋮ in the top-right corner.
4. Tap **Add to Home screen** (sometimes shown as **Install app**).
5. Accept the default name. Tap **Add**.

### 4. Save Photos to your home screen

1. In Chrome, paste the **Photos** URL.
2. Three dots ⋮ → **Add to Home screen** → **Add**.

Two icons now live on your home screen.

---

## Day-to-day — writing a listing from your phone

Once setup is done, this is the whole flow.

### 1. Open the chat

Tap **Harcourts Listings** on your home screen.

### 2. Pick yourself

You'll see a numbered list of consultants. Reply with your name or number. Then type your email when asked. (The email is just so we know who created the listing — it isn't a login.)

### 3. Tell the assistant the address

The assistant will ask for the full property address. Type it in.

### 4. Upload your photos and floor plan

The assistant will give you a link that looks like the Photos URL but with extra parts on the end — that link is specific to this property.

1. Tap or copy the link the assistant just sent you.
2. The Photos page opens (or switch to it from your home screen).
3. Tap **Tap to choose photos**.
4. In the photo picker, tap each photo you want to include. Tap the floor plan too if you have it as a photo or PDF.
5. Tap **Choose** (or **Done**) to finish picking.
6. Tap **Upload**. Wait for the progress bar to fill and the page to say **Done. Uploaded N files.**

### 5. Tell the assistant you're back

Switch back to **Harcourts Listings** (just tap its icon on the home screen, or use the app switcher).

Tell the assistant something like: *"All uploaded — 8 photos and the floor plan."*

The assistant will count what it sees and either confirm or ask a follow-up.

### 6. Follow the assistant the rest of the way

The assistant will walk you through five steps: a quick briefing on the property, the listing description, the brochure text, the social media caption, and the final Word document. After each step it asks you to approve before moving on. There's nothing more you need to remember.

---

## Other ways to get photos onto the Mac

The **Photos** page works on any device, but if it's down or you want an alternative, any of these also work. The assistant in the chat will offer them as fallbacks if needed.

### iPhone: AirDrop (only in the office)

If you're standing near the office Mac:

1. Open **Photos** on your iPhone.
2. Select the photos you want to send.
3. Tap the **Share** icon → **AirDrop**.
4. Pick the Mac (it's named **Harcourts** or similar).
5. The Mac will save them to its **Downloads** folder. Tell the assistant they're there and it will move them into the right session.

### Drop into iCloud Drive

If your phone is signed into the same iCloud account as the Mac:

1. Open **Photos** on your iPhone.
2. Share → **Save to Files**.
3. Pick the folder the admin set up (usually called **Harcourts Inbox**) inside iCloud Drive.
4. Tell the assistant.

### Email the photos

In a pinch, email the photos to your own email account, then open that email on the Mac and save the attachments into the session folder. Clunky, but it always works.

---

## Troubleshooting

### "The page won't load"

1. Open **Tailscale** on your phone. Is it green and **Connected**?
2. If not, tap the toggle to reconnect. If you can't reconnect, sign out and sign in again.
3. Still nothing? Open a separate browser tab and type `http://harcourts-mac.tail-xxxx.ts.net:8080/healthz` (with the correct address from the admin). If you see `{"ok":true,…}` the Mac is up; if you don't, the Mac itself is off — call the admin.

### "The chat is stuck or frozen"

1. Close the **Harcourts Listings** tab.
2. Tap the icon again from your home screen.
3. You'll be back at the start. Pick yourself again and tell the assistant which property you were working on — it will find the session folder you already created.

### "Upload says 'Session folder does not exist'"

You opened the **Photos** link before starting the listing in the chat. Open **Harcourts Listings** first, give it the address, then come back to the upload link the assistant gives you.

### "The Mac is off"

The system needs the office Mac running and logged in. If you suspect it's off or asleep, contact the admin. There's no remote-wake feature in this build.

### "My HEIC photos aren't showing up properly"

iPhone photos in HEIC format are converted to JPEG automatically when you upload them. If you ever see a HEIC file still in your session folder, the conversion didn't run — let the admin know so they can fix it on the Mac. You don't need to change your iPhone settings.

### "I uploaded to the wrong session"

Tell the assistant in the chat. It can move the files to the correct session folder, or delete them and ask you to re-upload.

---

## A printable summary

Keep this near the desk if it helps.

> 1. Tap **Harcourts Listings**.
> 2. Pick your name. Type your email.
> 3. Type the property address.
> 4. Tap the upload link the assistant gives you.
> 5. Choose all the photos and the floor plan. Tap **Upload**. Wait for **Done**.
> 6. Tap **Harcourts Listings** again. Tell the assistant you're back.
> 7. Approve each step the assistant shows you.
> 8. At the end, the assistant tells you where the final Word document is saved on the Mac.

import type { Metadata, Viewport } from "next";
import { Source_Sans_3 } from "next/font/google";

import "./globals.css";

// Harcourts brand typography — Source Sans Pro (the modern Google
// Fonts name is "Source Sans 3"). Loaded via next/font so it's
// self-hosted at build time, no flash of unstyled text, no external
// network call at render. Exposed as a CSS variable so globals.css
// can pick it up for `body { font-family: var(--font-source-sans) }`.
const sourceSans = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-source-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Harcourts Listing Generator",
  description: "Property listing content in each consultant's voice.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sourceSans.variable} h-full`}>
      <body className="h-full bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}

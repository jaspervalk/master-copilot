import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";

import { AppShell } from "@/components/shell/app-shell";
import { THEME_SCRIPT } from "@/lib/theme";

import "katex/dist/katex.min.css";
import "./globals.css";


const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  axes: ["opsz", "SOFT"],
});


export const metadata: Metadata = {
  title: "Master Copilot",
  description: "Vragen stellen over je eigen studiemateriaal, met vindplaats.",
};


export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // Het script hieronder zet `dark` op <html> voordat React hydrateert, en
    // de server kan niet weten of dat gebeurt. De onderdrukking geldt alleen
    // voor de attributen van <html> zelf, net als bij <body>.
    <html lang="nl" className={`${sans.variable} ${display.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      {/* Browserextensies (thema's, leesmodus) zetten attributen op <body> voordat
          React hydrateert — waargenomen: data-rm-theme="light". Dat levert een
          hydratiewaarschuwing op over iets wat wij niet renderen en niet kunnen
          voorkomen. De onderdrukking geldt alleen voor dit ene element, niet voor
          wat erin staat, dus een echte mismatch in de app blijft zichtbaar. */}
      <body className="antialiased" suppressHydrationWarning>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";
import "./globals.css";

import { Shell } from "@/components/shell";

// BSA's pairing: Inter for body and labels, Poppins for every number, KPI and
// heading. Exposed as --font-sans / --font-mono (the old name, kept so no
// component changes) and consumed by globals.css + Tailwind.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["400", "500", "600"],
  display: "swap",
});

const poppins = Poppins({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["300", "400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Oscillator",
  description: "Capmob engineering: who shipped what, and whether it shipped on time.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${poppins.variable}`}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

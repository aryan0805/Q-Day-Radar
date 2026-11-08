import type { Metadata, Viewport } from "next";
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans-condensed/latin-400.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "../styles/globals.css";
import { SiteHeader } from "../components/SiteHeader";
import { SiteFooter } from "../components/SiteFooter";
import { LatticeField } from "../components/background/LatticeField";
import { ScenarioProvider } from "../lib/scenario";
import { FigTipHost } from "../components/FigTipHost";
import { EggLoader } from "../components/eggs/EggLoader";
import { TweakLoader } from "../components/TweakLoader";

export const metadata: Metadata = {
  title: { default: "Q-Day Radar", template: "%s · Q-Day Radar" },
  description:
    "Real Shor and Grover circuits, scaled into resource estimates, ranking a crypto inventory by how soon quantum computers could break it.",
};

export const viewport: Viewport = { themeColor: "#05070b", colorScheme: "dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ScenarioProvider>
        <LatticeField />
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" className="shell" style={{ paddingBlock: "2.5rem 4rem" }}>
          {children}
        </main>
        <SiteFooter />
        <TweakLoader />
        <EggLoader />
        <FigTipHost />
        </ScenarioProvider>
      </body>
    </html>
  );
}

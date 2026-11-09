"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ScenarioSwitch } from "./ScenarioSwitch";
import { useScenario, withScenario } from "../lib/scenario";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/lab/", label: "Lab" },
  { href: "/scaling/", label: "Scaling" },
  { href: "/inventory/", label: "Inventory" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  const { scenario } = useScenario();
  return (
    <header style={{ borderBottom: "1px solid var(--line)", background: "var(--bg-1)" }}>
      <div
        className="shell"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem 1.5rem",
          paddingBlock: "0.75rem",
        }}
      >
        <Link
          href={withScenario("/", scenario)}
          style={{
            fontFamily: "var(--font-cond)",
            fontWeight: 600,
            fontSize: "1.125rem",
            color: "var(--text-1)",
            textDecoration: "none",
          }}
        >
          Q-Day Radar
        </Link>
        <nav aria-label="Main">
          <ul style={{ display: "flex", gap: "0.25rem", margin: 0, padding: 0, listStyle: "none" }}>
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link
                  className="nav-link"
                  href={withScenario(l.href, scenario)}
                  aria-current={pathname === l.href ? "page" : undefined}
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <ScenarioSwitch />
      </div>
    </header>
  );
}

import Link from "next/link";

export default function NotFound() {
  return (
    <section aria-labelledby="nf">
      <h1 id="nf" style={{ fontSize: "2rem", marginBlock: "0 0.75rem" }}>
        Page not found
      </h1>
      <p className="muted">
        This page collapsed to |not found⟩ on observation. Before you looked, it was both here and
        not here. Use the navigation above, or go back to the <Link href="/">Overview</Link>.
      </p>
      <svg viewBox="0 0 320 90" role="img" aria-label="Two paths in superposition that collapse into one" className="nf-paths">
        <path className="nf-a" pathLength={1} d="M 10 45 C 90 5, 150 5, 160 45 S 230 85, 310 45" fill="none" stroke="var(--q)" strokeWidth="2" />
        <path className="nf-b" pathLength={1} d="M 10 45 C 90 85, 150 85, 160 45 S 230 5, 310 45" fill="none" stroke="var(--pqc)" strokeWidth="2" />
        <circle cx="310" cy="45" r="4" fill="var(--text-1)" />
      </svg>
    </section>
  );
}

import Link from "next/link";

export default function NotFound() {
  return (
    <section aria-labelledby="nf">
      <h1 id="nf" style={{ fontSize: "2rem", marginBlock: "0 0.75rem" }}>
        Page not found
      </h1>
      <p className="muted">
        This address does not exist on the site. Use the navigation above, or go back to the{" "}
        <Link href="/">Overview</Link>.
      </p>
    </section>
  );
}

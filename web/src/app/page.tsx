export default function Home() {
  return (
    <section aria-labelledby="h">
      <h1 id="h" style={{ fontSize: "2.25rem", marginBlock: "0 0.75rem" }}>
        Q-Day Radar
      </h1>
      <p className="muted">The overview radar is built in sub-phase 5b.</p>
      <p style={{ display: "flex", gap: "0.75rem", marginTop: "1.5rem" }}>
        <a className="btn" href="/lab/">
          Open the Lab
        </a>
        <a className="btn btn-safe" href="/inventory/">
          Open the Inventory
        </a>
      </p>
    </section>
  );
}

import type { Metadata } from "next";

export const metadata: Metadata = { title: "Lab" };

export default function Page() {
  return (
    <section aria-labelledby="h">
      <h1 id="h" style={{ fontSize: "2rem", marginBlock: "0 0.75rem" }}>
        Lab
      </h1>
      <p className="muted">This screen is built in sub-phase 5b.</p>
    </section>
  );
}

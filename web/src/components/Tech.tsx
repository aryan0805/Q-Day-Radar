import type { ReactNode } from "react";

/** The second layer of a section: the precise wording, kept in the page (and traced) but folded
 *  away so the plain explanation comes first. The gate scores the plain layer only. */
export function Tech({ children }: { children: ReactNode }) {
  return (
    <details data-layer="technical" className="tech">
      <summary>Technical detail</summary>
      <div className="tech-body">{children}</div>
    </details>
  );
}

import type { ReactNode } from "react";
import type { GLOSSARY } from "../lib/glossary";

/** Wraps a term at its first use on a page. Hover, focus or tap shows a plain definition (the shared
 *  FigTipHost draws it); Escape closes it. */
export function Gloss({ term, children }: { term: keyof typeof GLOSSARY; children: ReactNode }) {
  return (
    <span className="gloss" data-term={term} tabIndex={0} role="button" aria-haspopup="true">
      {children}
    </span>
  );
}

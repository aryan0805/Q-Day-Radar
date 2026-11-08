export function SiteFooter() {
  return (
    <footer style={{ borderTop: "1px solid var(--line)", background: "var(--bg-1)" }}>
      <div
        className="shell muted"
        style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "0.75rem 1.5rem", paddingBlock: "1.25rem", fontSize: "0.875rem" }}
      >
        <p style={{ margin: 0 }}>
          Every figure on these pages is read from files in <code>/data</code>. Hover or focus a
          figure to see where it comes from. <a href="/.well-known/security.txt">security.txt</a> ·{" "}
          <a href="/humans.txt">humans.txt</a>
        </p>
        <button type="button" className="coin" data-egg="coin">
          <span aria-hidden="true">|ψ⟩</span>
          <span className="sr-only">Measure a quantum coin</span>
        </button>
      </div>
    </footer>
  );
}

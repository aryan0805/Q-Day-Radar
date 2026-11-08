export function SiteFooter() {
  return (
    <footer style={{ borderTop: "1px solid var(--line)", background: "var(--bg-1)" }}>
      <div className="shell muted" style={{ paddingBlock: "1.25rem", fontSize: "0.875rem" }}>
        <p style={{ margin: 0 }}>
          Every figure on these pages is read from files in <code>/data</code>. Hover or focus a
          figure to see where it comes from.{" "}
          <a href="/.well-known/security.txt">security.txt</a> · <a href="/humans.txt">humans.txt</a>
        </p>
      </div>
    </footer>
  );
}

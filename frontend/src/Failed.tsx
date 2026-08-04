/**
 * One shape for "this panel could not load", so no surface ever renders a
 * confident empty state over a failure it swallowed.
 */
export function Failed({ what, detail }: { what: string; detail: string }) {
  return (
    <div className="empty">
      Couldn't load {what}. Is the cockpit server still running?
      <br />
      <span className="mono">{detail}</span>
    </div>
  );
}

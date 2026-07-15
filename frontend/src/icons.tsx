/**
 * The cockpit's icon set — hand-inlined SVG, no icon-font dependency.
 *
 * Every glyph draws on a 20x20 viewBox in `currentColor`, so the nav controls
 * colour by setting `color` on the wrapper. The seven-rayed star is Seshat's
 * emblem, drawn from the actual geometry rather than hard-coded points.
 */

const STAR_RAYS = Array.from({ length: 7 }).map((_, i) => {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / 7;
  return { x: (10 + 7.5 * Math.cos(a)).toFixed(1), y: (10 + 7.5 * Math.sin(a)).toFixed(1) };
});

export function Star({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden>
      <g stroke="var(--gold)" strokeWidth="1.4" strokeLinecap="round">
        {STAR_RAYS.map((p, i) => (
          <line key={i} x1="10" y1="10" x2={p.x} y2={p.y} />
        ))}
      </g>
      <circle cx="10" cy="10" r="2" fill="var(--gold)" />
    </svg>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden>
      {children}
    </svg>
  );
}

const TimelineIcon = () => (
  <Frame>
    <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <line x1="3" y1="6" x2="17" y2="6" />
      <line x1="3" y1="10" x2="13" y2="10" />
      <line x1="3" y1="14" x2="15" y2="14" />
    </g>
  </Frame>
);

const ChatIcon = () => (
  <Frame>
    <path
      d="M3.5 4.5h13a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H9l-3.5 3v-3H3.5a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1z"
      stroke="currentColor"
      strokeWidth="1.4"
      fill="none"
    />
  </Frame>
);

const PapersIcon = () => (
  <Frame>
    <g stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinejoin="round">
      <path d="M5 2.5h6l4 4v11H5z" />
      <path d="M11 2.5v4h4" />
    </g>
  </Frame>
);

const CodeIcon = () => (
  <Frame>
    <g
      stroke="currentColor"
      strokeWidth="1.6"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="7,6 3,10 7,14" />
      <polyline points="13,6 17,10 13,14" />
    </g>
  </Frame>
);

const DataIcon = () => (
  <Frame>
    <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <line x1="4" y1="15" x2="4" y2="11" />
      <line x1="10" y1="15" x2="10" y2="7" />
      <line x1="16" y1="15" x2="16" y2="4" />
    </g>
  </Frame>
);

export const ICONS = {
  timeline: TimelineIcon,
  chat: ChatIcon,
  papers: PapersIcon,
  code: CodeIcon,
  data: DataIcon,
};

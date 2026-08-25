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

/**
 * Glyphs used inside surfaces rather than in the nav.
 *
 * These replace the text characters the UI used to borrow — the evidence
 * toggle's triangle, the file tree's chevrons, the reader's back arrow — which
 * carried their own weight and baseline and never matched the drawn set.
 * Same 20x20 grid and `currentColor` convention as above; `size` exists
 * because these sit inline with text at several sizes.
 */
function Glyph({ size = 16, children }: { size?: number; children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden focusable="false">
      {children}
    </svg>
  );
}

export const Check = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <polyline
      points="4.5,10.5 8.2,14.2 15.5,5.8"
      stroke="currentColor"
      strokeWidth="1.8"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Glyph>
);

export const Pencil = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <g
      stroke="currentColor"
      strokeWidth="1.4"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M13.6 3.6l2.8 2.8-8.6 8.6H5v-2.8z" />
      <line x1="11.6" y1="5.6" x2="14.4" y2="8.4" />
    </g>
  </Glyph>
);

export const Undo = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <g
      stroke="currentColor"
      strokeWidth="1.5"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 7.5h6a4 4 0 0 1 0 8H7.5" />
      <polyline points="8.5,4.5 5.5,7.5 8.5,10.5" />
    </g>
  </Glyph>
);

/** Points down when open, right when closed. */
export const Chevron = ({ open, size = 11 }: { open: boolean; size?: number }) => (
  <Glyph size={size}>
    <polyline
      points={open ? "5,7.5 10,12.5 15,7.5" : "7.5,5 12.5,10 7.5,15"}
      stroke="currentColor"
      strokeWidth="1.6"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Glyph>
);

export const ArrowRight = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <g
      stroke="currentColor"
      strokeWidth="1.5"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="3.5" y1="10" x2="15" y2="10" />
      <polyline points="11,6 15.5,10 11,14" />
    </g>
  </Glyph>
);

export const ArrowLeft = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <g
      stroke="currentColor"
      strokeWidth="1.5"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="16.5" y1="10" x2="5" y2="10" />
      <polyline points="9,6 4.5,10 9,14" />
    </g>
  </Glyph>
);

export const Search = ({ size = 14 }: { size?: number }) => (
  <Glyph size={size}>
    <g stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round">
      <circle cx="8.5" cy="8.5" r="5" />
      <line x1="12.4" y1="12.4" x2="16.5" y2="16.5" />
    </g>
  </Glyph>
);

/** The journaling queue, for the status bar's stalled-queue pill. */
export const Queue = ({ size = 13 }: { size?: number }) => (
  <Glyph size={size}>
    <g stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round">
      <rect x="4" y="4" width="12" height="12" rx="2" />
      <line x1="8" y1="8" x2="12" y2="8" />
      <line x1="8" y1="12" x2="12" y2="12" />
    </g>
  </Glyph>
);

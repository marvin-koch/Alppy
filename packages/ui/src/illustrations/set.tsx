import { createIllustration } from './Illustration';

/* Three colours, never more. The accent marks exactly one point per drawing. */
const FILL = 'var(--c-primary-100)';
const ACCENT = 'var(--c-accent-500)';

/** The slate. Home, class, "nothing here yet". */
export const IlloSlate = createIllustration(
  'IlloSlate',
  <>
    <rect x="14" y="26" width="92" height="62" rx="7" fill={FILL} />
    <path d="M32 46h44M32 60h30" />
    <path d="M40 100h40M52 88v12M68 88v12" />
    <circle cx="86" cy="72" r="5" fill={ACCENT} stroke="none" />
  </>,
);

/** The compass. Building, planning, a sheet under construction. */
export const IlloCompass = createIllustration(
  'IlloCompass',
  <>
    <circle cx="60" cy="82" r="34" fill={FILL} stroke="none" />
    <path d="M60 18v10" />
    <path d="M60 28 38 96M60 28l22 68" />
    <path d="M45 74h30" />
    <circle cx="60" cy="24" r="6" />
    <circle cx="82" cy="96" r="5" fill={ACCENT} stroke="none" />
  </>,
);

/** The sheet. Worksheets, print preview, the deliverable. */
export const IlloSheet = createIllustration(
  'IlloSheet',
  <>
    <path d="M26 16h44l24 24v64H26z" fill={FILL} />
    <path d="M70 16v24h24" />
    <path d="M42 60h36M42 74h36M42 88h22" />
    <circle cx="88" cy="88" r="6" fill={ACCENT} stroke="none" />
  </>,
);

/** The forgetting curve. Mastery over time. */
export const IlloCurve = createIllustration(
  'IlloCurve',
  <>
    <path d="M20 24v72h80" />
    <path d="M28 34c22 4 34 22 40 38 4 11 8 18 14 22" fill="none" />
    <path d="M28 34c22 4 34 22 40 38 4 11 8 18 14 22H28Z" fill={FILL} stroke="none" />
    <path d="M28 34c22 4 34 22 40 38 4 11 8 18 14 22" />
    <circle cx="28" cy="34" r="6" fill={ACCENT} stroke="none" />
  </>,
);

/** The clock. Scheduling, revision due, waiting on a job. */
export const IlloClock = createIllustration(
  'IlloClock',
  <>
    <circle cx="60" cy="62" r="40" fill={FILL} />
    <path d="M60 38v24l16 11" />
    <path d="M44 14h32" />
    <circle cx="60" cy="62" r="5" fill={ACCENT} stroke="none" />
  </>,
);

/** The tray. Inbox, scans waiting, uploads. */
export const IlloTray = createIllustration(
  'IlloTray',
  <>
    <path d="M18 62h22l6 12h28l6-12h22v34a6 6 0 0 1-6 6H24a6 6 0 0 1-6-6z" fill={FILL} />
    <path d="M32 62 44 22h32l12 40" />
    <path d="M52 40h16" />
    <circle cx="60" cy="86" r="6" fill={ACCENT} stroke="none" />
  </>,
);

/** The cup. Done, rest, the Sunday-evening correction pile is empty. */
export const IlloCup = createIllustration(
  'IlloCup',
  <>
    <path d="M26 48h56v34a20 20 0 0 1-20 20H46a20 20 0 0 1-20-20z" fill={FILL} />
    <path d="M82 56h8a12 12 0 0 1 0 24h-8" />
    <path d="M46 20c-4 8 4 12 0 20M62 16c-4 10 4 14 0 24" />
    <circle cx="54" cy="72" r="6" fill={ACCENT} stroke="none" />
  </>,
);

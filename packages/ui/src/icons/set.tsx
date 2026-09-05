import { createIcon } from './Icon';

/* ==========================================================================
   The MVP icon set — drawn here, on a 24px grid, stroke 2.2, round caps and
   joins, `currentColor` only. No library, no borrowed marks (DESIGN.md §7).
   ========================================================================== */

/* — People & places ----------------------------------------------------- */

export const IconClass = createIcon(
  'IconClass',
  <>
    <circle cx="9" cy="8.5" r="3.2" />
    <path d="M2.8 19.5c0-3.1 2.8-4.8 6.2-4.8s6.2 1.7 6.2 4.8" />
    <path d="M16.4 5.9a3.2 3.2 0 0 1 0 5.2" />
    <path d="M17.6 14.9c2.2.5 3.6 2 3.6 4.6" />
  </>,
);

export const IconStudent = createIcon(
  'IconStudent',
  <>
    <circle cx="12" cy="8" r="3.6" />
    <path d="M4.8 20c0-3.6 3.2-5.6 7.2-5.6s7.2 2 7.2 5.6" />
  </>,
);

/* — Corpus & paper ------------------------------------------------------ */

export const IconBook = createIcon(
  'IconBook',
  <>
    <path d="M12 7.4C10.4 5.9 8 5.4 4.6 5.4v11.9c3.4 0 5.8.5 7.4 2 1.6-1.5 4-2 7.4-2V5.4c-3.4 0-5.8.5-7.4 2Z" />
    <path d="M12 7.4v11.9" />
  </>,
);

export const IconSheet = createIcon(
  'IconSheet',
  <>
    <path d="M13.6 3H7.2a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h9.6a1 1 0 0 0 1-1V7.4Z" />
    <path d="M13.6 3v4.4H18" />
    <path d="M9.4 12.6h5.2M9.4 16.4h3.4" />
  </>,
);

export const IconPrinter = createIcon(
  'IconPrinter',
  <>
    <path d="M7.4 9V3.8h9.2V9" />
    <path d="M7.4 18H5.2a1.2 1.2 0 0 1-1.2-1.2v-4.6A2.2 2.2 0 0 1 6.2 10h11.6a2.2 2.2 0 0 1 2.2 2.2v4.6a1.2 1.2 0 0 1-1.2 1.2h-2.2" />
    <path d="M7.4 14.8h9.2v5.4H7.4z" />
  </>,
);

export const IconUpload = createIcon(
  'IconUpload',
  <>
    <path d="M12 19.4V7.6" />
    <path d="M7.8 11.8 12 7.6l4.2 4.2" />
    <path d="M4.4 16.6v2.2a1.6 1.6 0 0 0 1.6 1.6h12a1.6 1.6 0 0 0 1.6-1.6v-2.2" />
  </>,
);

export const IconDownload = createIcon(
  'IconDownload',
  <>
    <path d="M12 4.6v11.8" />
    <path d="M7.8 12.2 12 16.4l4.2-4.2" />
    <path d="M4.4 16.6v2.2a1.6 1.6 0 0 0 1.6 1.6h12a1.6 1.6 0 0 0 1.6-1.6v-2.2" />
  </>,
);

/* — Scan path ----------------------------------------------------------- */

export const IconScan = createIcon(
  'IconScan',
  <>
    <path d="M4 8.4V6.2A2.2 2.2 0 0 1 6.2 4h2.2" />
    <path d="M15.6 4h2.2A2.2 2.2 0 0 1 20 6.2v2.2" />
    <path d="M20 15.6v2.2a2.2 2.2 0 0 1-2.2 2.2h-2.2" />
    <path d="M8.4 20H6.2A2.2 2.2 0 0 1 4 17.8v-2.2" />
    <path d="M4 12h16" />
  </>,
);

export const IconCamera = createIcon(
  'IconCamera',
  <>
    <path d="M3.2 9.8a1.4 1.4 0 0 1 1.4-1.4h2.2l1.5-2.2h7.4l1.5 2.2h2.2a1.4 1.4 0 0 1 1.4 1.4v8.2a1.4 1.4 0 0 1-1.4 1.4H4.6a1.4 1.4 0 0 1-1.4-1.4Z" />
    <circle cx="12" cy="13.4" r="3.4" />
  </>,
);

/* — Marking ------------------------------------------------------------- */

export const IconCheck = createIcon('IconCheck', <path d="m4.6 12.6 4.6 4.6L19.4 6.8" />);

export const IconCross = createIcon(
  'IconCross',
  <>
    <path d="M6.4 6.4 17.6 17.6" />
    <path d="M17.6 6.4 6.4 17.6" />
  </>,
);

export const IconClose = createIcon(
  'IconClose',
  <>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M9.2 9.2 14.8 14.8M14.8 9.2 9.2 14.8" />
  </>,
);

/* — Direction ----------------------------------------------------------- */

export const IconChevronUp = createIcon('IconChevronUp', <path d="m5.6 15.2 6.4-6.4 6.4 6.4" />);
export const IconChevronDown = createIcon('IconChevronDown', <path d="m5.6 8.8 6.4 6.4 6.4-6.4" />);
export const IconChevronLeft = createIcon('IconChevronLeft', <path d="m15.2 5.6-6.4 6.4 6.4 6.4" />);
export const IconChevronRight = createIcon('IconChevronRight', <path d="m8.8 5.6 6.4 6.4-6.4 6.4" />);

/* — Editing ------------------------------------------------------------- */

export const IconPlus = createIcon('IconPlus', <path d="M12 5.2v13.6M5.2 12h13.6" />);
export const IconMinus = createIcon('IconMinus', <path d="M5.2 12h13.6" />);

export const IconTrash = createIcon(
  'IconTrash',
  <>
    <path d="M4.2 6.8h15.6" />
    <path d="M9.4 6.8V5.2a1.2 1.2 0 0 1 1.2-1.2h2.8a1.2 1.2 0 0 1 1.2 1.2v1.6" />
    <path d="M6.4 6.8 7.5 19a2 2 0 0 0 2 1.8h5a2 2 0 0 0 2-1.8l1.1-12.2" />
    <path d="M10.4 10.6v6M13.6 10.6v6" />
  </>,
);

export const IconEdit = createIcon(
  'IconEdit',
  <>
    <path d="M15.4 5.4 18.6 8.6" />
    <path d="M4 20.2 4.9 16 15.9 5a2.2 2.2 0 0 1 3.1 3.1L8 19.1Z" />
  </>,
);

export const IconSearch = createIcon(
  'IconSearch',
  <>
    <circle cx="10.8" cy="10.8" r="6.2" />
    <path d="m15.4 15.4 4.4 4.4" />
  </>,
);

export const IconFilter = createIcon(
  'IconFilter',
  <>
    <path d="M4.4 6.4h15.2M7.4 12h9.2M10.2 17.6h3.6" />
  </>,
);

export const IconSettings = createIcon(
  'IconSettings',
  <>
    <path d="M4 8.4h9M18.4 8.4h1.6" />
    <circle cx="15.6" cy="8.4" r="2.4" />
    <path d="M4 15.6h1.6M11 15.6h9" />
    <circle cx="8.4" cy="15.6" r="2.4" />
  </>,
);

export const IconDragHandle = createIcon(
  'IconDragHandle',
  <>
    <circle cx="9.2" cy="6.6" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="14.8" cy="6.6" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="9.2" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="14.8" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="9.2" cy="17.4" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="14.8" cy="17.4" r="1.2" fill="currentColor" stroke="none" />
  </>,
);

export const IconMenu = createIcon('IconMenu', <path d="M4 7h16M4 12h16M4 17h16" />);

/* — Preferences (the four switches, DESIGN.md §8) ------------------------ */

export const IconSun = createIcon(
  'IconSun',
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.8v2.4M12 18.8v2.4M4.5 4.5l1.7 1.7M17.8 17.8l1.7 1.7M2.8 12h2.4M18.8 12h2.4M4.5 19.5l1.7-1.7M17.8 6.2l1.7-1.7" />
  </>,
);

export const IconMoon = createIcon(
  'IconMoon',
  <path d="M20 14.6A8.6 8.6 0 0 1 9.4 4 8.6 8.6 0 1 0 20 14.6Z" />,
);

export const IconContrast = createIcon(
  'IconContrast',
  <>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 3.6a8.4 8.4 0 0 0 0 16.8Z" fill="currentColor" stroke="none" />
  </>,
);

/* — AI. The sparkle is the only icon that ever sits on the mandarin. ----- */

export const IconSparkle = createIcon(
  'IconSparkle',
  <>
    <path d="m10.4 3.6 1.7 4.6 4.6 1.7-4.6 1.7-1.7 4.6-1.7-4.6L4.1 9.9l4.6-1.7Z" />
    <path d="m17.6 15.2.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9Z" />
  </>,
);

/* — Status & measurement ------------------------------------------------ */

export const IconWarning = createIcon(
  'IconWarning',
  <>
    <path d="M12 4.2 21 19.8H3Z" />
    <path d="M12 10v4" />
    <path d="M12 17.1h.01" />
  </>,
);

export const IconInfo = createIcon(
  'IconInfo',
  <>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 11.2V16" />
    <path d="M12 7.9h.01" />
  </>,
);

export const IconClock = createIcon(
  'IconClock',
  <>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 7.2V12l3.2 2" />
  </>,
);

export const IconChart = createIcon(
  'IconChart',
  <>
    <path d="M4 19.6h16" />
    <path d="M7.6 19.6v-5.2M12 19.6V8.4M16.4 19.6v-7.6" />
  </>,
);

export const IconTarget = createIcon(
  'IconTarget',
  <>
    <circle cx="12" cy="12" r="8.4" />
    <circle cx="12" cy="12" r="4.2" />
    <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
  </>,
);

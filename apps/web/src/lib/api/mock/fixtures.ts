/**
 * Fixture data for the mock layer. Deterministic on purpose: the screenshot
 * tests compare pixels, so ids, dates and scores must never move.
 *
 * Shapes come from `alppy/schemas`; nothing here invents a field.
 */
import type {
  AdaptiveProposeResponse,
  ChapterOut,
  ClassOut,
  ClassPointsOut,
  ClassTreeOut,
  CompetencyAttemptsOut,
  CompetencyOut,
  DetectionOut,
  ExerciseOut,
  ExerciseProposal,
  ExerciseType,
  HomeOut,
  MasteryBandKey,
  MasteryMatrixOut,
  ScanOut,
  SheetMasteryOut,
  SheetOut,
  SheetTakenOut,
  SourceOut,
  SourceSectionOut,
  StudentOut,
  StudentProfileOut,
  SubjectOut,
  TeacherOut,
  TimelineOut,
  TreeThemeOut
} from '../types';

const NOW = '2026-03-16T08:00:00+01:00';

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

export const teacher: TeacherOut = {
  id: id(1),
  email: 'claire.fontaine@example.ch',
  first_name: 'Claire',
  last_name: 'Fontaine',
  school_id: id(2),
  // Two staffrooms, so the screenshot suite covers the school row rather than
  // only the single-school case where it is deliberately hidden (D74).
  schools: [
    { id: id(2), name: 'Collège de démonstration', canton: 'VD', default_curriculum: 'PER' },
    { id: id(3), name: 'Oberstufe Chur', canton: 'GR', default_curriculum: 'LP21' },
  ],
  preferences: { locale: 'fr', theme: null, contrast: null, motion: null, calm: null },
};

export const subjects: SubjectOut[] = [
  { id: id(10), key: 'maths', labels: { fr: 'Mathématiques', de: 'Mathematik', en: 'Mathematics' } },
  { id: id(11), key: 'french', labels: { fr: 'Français', de: 'Französisch', en: 'French' } },
];

export const classes: ClassOut[] = [
  { id: id(20), code: '7B', label: 'Classe de Mme Fontaine', student_count: 18, subject_ids: [id(10), id(11)] },
  { id: id(21), code: '9A', label: null, student_count: 21, subject_ids: [id(10)] },
];

const NAMES: Array<[string, string]> = [
  ['Léa', 'Aebischer'], ['Noah', 'Berger'], ['Emma', 'Chevalley'], ['Liam', 'Dubois'],
  ['Chloé', 'Egger'], ['Nino', 'Ferrari'], ['Alice', 'Girard'], ['Elias', 'Huber'],
  ['Sofia', 'Isler'], ['Théo', 'Jaquet'], ['Mila', 'Kohler'], ['Louis', 'Lambert'],
  ['Zoé', 'Meyer'], ['Adam', 'Nicolet', ], ['Anna', 'Oberli'], ['Gabriel', 'Perret'],
  ['Nora', 'Quinche'], ['Samuel', 'Rossier'],
];

export const students: StudentOut[] = NAMES.map(([first, last], index) => {
  // The last pupil is homed in 9A and sits in 7B as well. A fixture where
  // everybody is a plain member could never show that a visitor keeps the
  // identifier their own class minted (D69) — which is the one thing about
  // enrollment a teacher has to be able to see.
  const visiting = index === NAMES.length - 1;
  const home = visiting ? '9A' : '7B';
  return {
    id: id(100 + index),
    uid: `${home}_${String(index + 1).padStart(2, '0')}`,
    number: index + 1,
    first_name: first,
    last_name: last ?? '',
    home_class_code: home,
    class_codes: visiting ? ['9A', '7B'] : ['7B'],
  };
});

export const competencies: CompetencyOut[] = [
  ['MSN 32', 'Fractions et décimaux', 'Brüche und Dezimalzahlen', 'Fractions and decimals'],
  ['MSN 33', 'Proportionnalité', 'Proportionalität', 'Proportionality'],
  ['MSN 34', 'Calcul littéral', 'Termumformungen', 'Algebraic expressions'],
  ['MSN 35', 'Équations du 1er degré', 'Lineare Gleichungen', 'Linear equations'],
  ['MSN 36', 'Aires et périmètres', 'Flächen und Umfänge', 'Area and perimeter'],
  ['MSN 37', 'Théorème de Pythagore', 'Satz des Pythagoras', 'Pythagorean theorem'],
  ['MSN 38', 'Statistiques descriptives', 'Beschreibende Statistik', 'Descriptive statistics'],
].map(([code, fr, de, en], index) => ({
  id: id(200 + index),
  curriculum: 'PER' as const,
  code: code ?? '',
  parent_id: null,
  subject_key: 'maths',
  cycle: 3,
  labels: { fr: fr ?? '', de: de ?? '', en: en ?? '' },
  description: {},
}));

export const chapters: ChapterOut[] = [
  ['fractions', 'Fractions', 'Brüche', 'Fractions', [0]],
  ['proportion', 'Proportionnalité', 'Proportionalität', 'Proportionality', [1]],
  ['algebra', 'Calcul littéral et équations', 'Algebra und Gleichungen', 'Algebra and equations', [2, 3]],
  ['geometry', 'Géométrie plane', 'Ebene Geometrie', 'Plane geometry', [4, 5]],
].map(([key, fr, de, en, refs], index) => ({
  id: id(300 + index),
  key: String(key),
  labels: { fr: String(fr), de: String(de), en: String(en) },
  position: index,
  competency_ids: (refs as number[]).map((r) => id(200 + r)),
  // The Competence this Theme hangs from: the first code it tags, as the seed
  // loader resolves it for a PER school.
  primary_competency_id: id(200 + (refs as number[])[0]) as string | null,
})).concat([
  {
    // The per-subject `unfiled` bucket. It exists in every real school and the
    // settings screen explains it, so a mock without one showed a sentence
    // about a row that was not there.
    //
    // `primary_competency_id: null` is what keeps it out of the tree and
    // undeletable — the key alone would not, because a school may relabel it.
    id: id(299),
    key: 'unfiled',
    labels: { fr: 'Non classé', de: 'Nicht zugeordnet', en: 'Unfiled' },
    position: 999,
    competency_ids: [],
    primary_competency_id: null,
  },
]);

/**
 * The curriculum tree, built from the chapters above so the mock cannot drift
 * from them. Each chapter's primary competency stands in for its Competence —
 * these fixtures have no competency parents, and D56's documented fallback is
 * that a top-level primary is its own Competence node.
 */
export function classTree(classId: string): ClassTreeOut {
  const bands: MasteryBandKey[] = ['solid', 'ok', 'weak', 'fading'];
  const themeOf = (chapter: ChapterOut, index: number): TreeThemeOut => ({
    chapter_id: chapter.id,
    key: chapter.key,
    labels: chapter.labels,
    position: chapter.position,
    sheet_count: (index % 3) + 1,
    competency_ids: chapter.competency_ids,
    mastery: {
      score: 0.9 - index * 0.12,
      band: bands[index % bands.length] as MasteryBandKey,
      attempts_count: 12 - index,
      provisional: false,
      assessed_count: Math.max(1, chapter.competency_ids.length - (index % 2)),
      child_count: chapter.competency_ids.length,
      weakest_band: bands[index % bands.length] as MasteryBandKey,
      days_until_review: 7 + index,
      last_attempt_at: NOW,
    },
  });

  return {
    class_id: classId,
    computed_at: NOW,
    branches: [
      {
        subject_id: id(10),
        subject_key: 'mathematics',
        labels: { fr: 'Mathématiques', de: 'Mathematik', en: 'Mathematics' },
        mastery: {
          score: 0.72,
          band: 'weak',
          attempts_count: 38,
          provisional: false,
          assessed_count: 4,
          child_count: 4,
          weakest_band: 'fading',
          days_until_review: 5,
          last_attempt_at: NOW,
        },
        // The `unfiled` bucket is excluded from the tree by
        // `primary_competency_id === null`, never by its key — the same two
        // tests `tree_service` applies, because a school may relabel it. A
        // mock that mapped every chapter would have invented a Competence
        // called "Non classé" and put its sheets back into a mastery number.
        competences: chapters
          .filter((chapter) => chapter.primary_competency_id !== null)
          .map((chapter, index) => ({
          competency_id: chapter.primary_competency_id ?? id(200 + index),
          code: competencies[index]?.code ?? `MSN 3${index + 1}`,
          labels: competencies[index]?.labels ?? chapter.labels,
          mastery: themeOf(chapter, index).mastery,
          themes: [themeOf(chapter, index)],
          })),
        unfiled_sheet_count: 2,
        // Rendered even at zero in the picker; non-zero here so the mock shows
        // the counted bucket the constraint requires (DC-content-06).
        unfiled_exercise_count: 3,
      },
    ],
  };
}

/* Deterministic pseudo-random, so the matrix looks real and never moves. */
function pseudoScore(studentIndex: number, competencyIndex: number): number {
  const seed = (studentIndex * 37 + competencyIndex * 91 + 13) % 100;
  return Math.round((0.35 + (seed / 100) * 0.62) * 100) / 100;
}

function bandOf(score: number): MasteryMatrixOut['cells'][number]['band'] {
  if (score >= 0.9) return 'solid';
  if (score >= 0.75) return 'ok';
  if (score >= 0.6) return 'weak';
  return 'fading';
}

export const masteryMatrix: MasteryMatrixOut = {
  class_id: id(20),
  students,
  competencies,
  cells: students.flatMap((student, si) =>
    competencies.flatMap((competency, ci) => {
      // Some pairs were never assessed: `none` is a real band, and the fixture
      // has to send it exactly as the API does — a row with band 'none',
      // attempts_count 0 and score 0. Omitting the cell instead let the UI fall
      // back to a null score, which hid the fact that the real payload made a
      // never-assessed cell render a bold "0".
      const seen = (si + ci) % 17 !== 0;
      const score = seen ? pseudoScore(si, ci) : 0;
      return [
        {
          student_id: student.id,
          competency_id: competency.id,
          score,
          band: seen ? bandOf(score) : ('none' as const),
          attempts_count: seen ? ((si + ci) % 6) + 1 : 0,
          provisional: seen ? ((si + ci) % 6) + 1 < 3 : true,
          days_until_review: seen ? (score >= 0.75 ? ((si * ci) % 9) + 1 : 0) : null,
          last_attempt_at: seen ? '2026-03-09T10:15:00+01:00' : null,
        },
      ];
    }),
  ),
  computed_at: NOW,
};

/**
 * The matrix as the endpoint serves it, honouring `chapter_id` and `sort`.
 *
 * The mock has to narrow and re-order for real, or an e2e test cannot tell a
 * working filter from a control that renders and does nothing.
 */
export function classMastery(classId: string, query: URLSearchParams): MasteryMatrixOut {
  const chapterId = query.get('chapter_id');
  const sort = query.get('sort');

  let shown = competencies;
  if (chapterId) {
    const chapter = chapters.find((c) => c.id === chapterId);
    const allowed = new Set(chapter?.competency_ids ?? []);
    shown = competencies.filter((c) => allowed.has(c.id));
  }
  const shownIds = new Set(shown.map((c) => c.id));
  const cells = masteryMatrix.cells.filter((c) => shownIds.has(c.competency_id));

  let roster = students;
  if (sort === 'weakest') {
    // Worst assessed cell first; a student with nothing assessed sorts last,
    // because "never taught" is not a weakness.
    const worst = new Map<string, number>();
    for (const cell of cells) {
      if (cell.band === 'none') continue;
      const current = worst.get(cell.student_id);
      if (current === undefined || cell.score < current) worst.set(cell.student_id, cell.score);
    }
    roster = [...students].sort((a, b) => {
      const wa = worst.get(a.id);
      const wb = worst.get(b.id);
      if (wa === undefined && wb === undefined) return a.number - b.number;
      if (wa === undefined) return 1;
      if (wb === undefined) return -1;
      return wa - wb || a.number - b.number;
    });
  }

  const order = new Map(roster.map((s, i) => [s.id, i]));
  return {
    ...masteryMatrix,
    class_id: classId,
    students: roster,
    competencies: shown,
    cells: [...cells].sort(
      (a, b) => (order.get(a.student_id) ?? 0) - (order.get(b.student_id) ?? 0),
    ),
  };
}

export const home: HomeOut = {
  teacher,
  subjects,
  classes: [
    {
      class_id: id(20),
      code: '7B',
      label: 'Classe de Mme Fontaine',
      student_count: 18,
      last_sheet_title: 'Fractions — révision avant le test',
      last_sheet_at: '2026-03-12T14:30:00+01:00',
      pending_scans: 2,
      students_needing_attention: 4,
      band_counts: { solid: 31, ok: 38, weak: 27, fading: 18, none: 12 },
    },
    {
      class_id: id(21),
      code: '9A',
      label: null,
      student_count: 21,
      last_sheet_title: null,
      last_sheet_at: null,
      pending_scans: 0,
      students_needing_attention: 0,
      band_counts: { solid: 0, ok: 0, weak: 0, fading: 0, none: 147 },
    },
  ],
};

export const sources: SourceOut[] = [
  {
    id: id(400),
    subject_id: id(10),
    filename: 'mathematiques-9e-cycle3.pdf',
    title: 'Mathématiques 9e — cycle 3',
    content_type: 'application/pdf',
    size_bytes: 18_432_100,
    language: 'fr',
    page_count: 244,
    status: 'succeeded',
    error: null,
    notice: null,
    exercise_count: 312,
    section_count: 9,
    created_at: '2026-02-28T09:12:00+01:00',
  },
  {
    id: id(401),
    subject_id: id(10),
    filename: 'cahier-exercices-fractions.pdf',
    title: null,
    content_type: 'application/pdf',
    size_bytes: 4_120_400,
    language: 'fr',
    page_count: 48,
    status: 'running',
    error: null,
    notice: null,
    exercise_count: 0,
    section_count: 0,
    created_at: '2026-03-16T07:55:00+01:00',
  },
];

/** The book's own table of contents.
 *
 *  Three states are represented deliberately: read, never read (the on-demand
 *  door), and the un-headed tail that must never be hidden. */
export const sourceSections: SourceSectionOut[] = [
  {
    id: id(600),
    title: 'Les fractions',
    label: '4',
    page_from: 78,
    page_to: 112,
    position: 0,
    exercise_count: 186,
    extracted_at: '2026-02-28T09:14:00+01:00',
    extraction_notice: null,
  },
  {
    id: id(601),
    title: 'Proportionnalité',
    label: '5',
    page_from: 113,
    page_to: 140,
    position: 1,
    exercise_count: 126,
    extracted_at: '2026-02-28T09:15:00+01:00',
    extraction_notice: null,
  },
  {
    id: id(602),
    title: 'Géométrie plane',
    label: '6',
    page_from: 141,
    page_to: 178,
    position: 2,
    exercise_count: 0,
    extracted_at: null,
    extraction_notice: null,
  },
  {
    id: id(603),
    title: 'Théorème de Pythagore',
    label: '7',
    page_from: 179,
    page_to: 210,
    position: 3,
    exercise_count: 0,
    extracted_at: null,
    extraction_notice: null,
  },
  {
    id: id(604),
    title: 'p. 211–244',
    label: null,
    page_from: 211,
    page_to: 244,
    position: 4,
    exercise_count: 0,
    extracted_at: null,
    extraction_notice: null,
  },
];

function exercise(index: number, overrides: Partial<ExerciseOut> = {}): ExerciseOut {
  return {
    id: id(500 + index),
    type: 'mcq',
    origin: 'textbook',
    language: 'fr',
    statement: `Calcule ${index + 2}/4 + 1/3 et donne le résultat sous forme irréductible.`,
    options: ['11/12', '3/7', '5/12', '7/12'],
    answer_index: 0,
    answer_bool: null,
    answer_text: null,
    explanation: 'Mise au même dénominateur : 12.',
    difficulty: (index % 5) + 1,
    chapter_id: id(300),
    competency_ids: [id(200)],
    source_id: id(400),
    source_section_id: id(600),
    source_page: 84 + index,
    label: null,
    title: null,
    figure_url: null,
    figure_width_mm: null,
    figure_height_mm: null,
    approved_at: null,
    ...overrides,
  };
}

export const exercises: ExerciseOut[] = [
  exercise(0),
  exercise(1, {
    type: 'true_false',
    statement: "Une fraction dont le numérateur est plus grand que le dénominateur est supérieure à 1.",
    options: null,
    answer_index: null,
    answer_bool: true,
  }),
  exercise(2, { statement: 'Simplifie la fraction 18/24.', options: ['3/4', '9/12', '2/3', '6/8'] }),
  exercise(3, {
    type: 'open',
    statement: "Explique avec tes mots pourquoi 0,25 et 1/4 représentent la même quantité.",
    options: null,
    answer_index: null,
    answer_text: 'Réponse libre.',
  }),
  exercise(4, { statement: 'Convertis 3/8 en écriture décimale.', options: ['0,375', '0,38', '0,83', '2,67'] }),
  exercise(5, { statement: 'Range dans l’ordre croissant : 2/3 ; 0,6 ; 5/8.', options: ['0,6 < 5/8 < 2/3', '2/3 < 0,6 < 5/8', '5/8 < 0,6 < 2/3', '0,6 < 2/3 < 5/8'] }),
  // A second populated chapter, so the outline shows more than one state that
  // matters and switching chapters visibly changes the list.
  ...Array.from({ length: 9 }, (_, i) =>
    exercise(60 + i, {
      id: id(640 + i),
      type: i % 2 === 0 ? 'mcq' : 'true_false',
      statement: `Proportionnalité — exercice ${i + 1} du chapitre.`,
      options: i % 2 === 0 ? ['A', 'B', 'C', 'D'] : null,
      answer_index: i % 2 === 0 ? i % 4 : null,
      answer_bool: i % 2 === 1 ? i % 3 === 0 : null,
      source_section_id: id(601),
      source_page: 113 + i,
    }),
  ),
  // Enough to make the picker's paginator do real work. A chapter of six would
  // let a broken "next page" pass: the control would simply never appear.
  ...Array.from({ length: 26 }, (_, i) =>
    exercise(10 + i, {
      id: id(560 + i),
      type: i % 3 === 0 ? 'mcq' : i % 3 === 1 ? 'true_false' : 'open',
      statement: `Fractions — exercice ${i + 7} du chapitre.`,
      options: i % 3 === 0 ? ['A', 'B', 'C', 'D'] : null,
      answer_index: i % 3 === 0 ? i % 4 : null,
      answer_bool: i % 3 === 1 ? i % 2 === 0 : null,
      answer_text: i % 3 === 2 ? 'Réponse libre.' : null,
      source_page: 78 + (i % 12),
    }),
  ),
];

const aiExercise: ExerciseOut = exercise(20, {
  origin: 'ai_generated',
  statement: 'Léa partage 3/4 d’une tarte entre 6 personnes. Quelle fraction reçoit chacune ?',
  options: ['1/8', '1/6', '3/24', '1/4'],
  answer_index: 0,
  source_id: null,
  source_page: null,
  approved_at: null,
});

function proposal(ex: ExerciseOut, score: number, reason: string): ExerciseProposal {
  return {
    exercise: ex,
    score,
    provenance: {
      source_id: ex.source_id,
      source_filename: ex.source_id ? 'mathematiques-9e-cycle3.pdf' : null,
      page: ex.source_page,
      excerpt:
        ex.source_id === null
          ? 'Généré à partir des compétences ciblées, sans extrait source.'
          : "Additionner deux fractions demande de les réduire au même dénominateur avant d’additionner les numérateurs.",
      similarity: ex.source_id ? score : null,
      reason,
    },
  };
}

export const proposals: ExerciseProposal[] = [
  proposal(exercises[0] as ExerciseOut, 0.92, 'Correspond à l’intention et à MSN 32.'),
  proposal(exercises[2] as ExerciseOut, 0.88, 'Simplification : prérequis de l’addition.'),
  proposal(exercises[4] as ExerciseOut, 0.81, 'Passage fraction/décimal, chapitre sélectionné.'),
  proposal(exercises[1] as ExerciseOut, 0.77, 'Vrai/faux rapide en ouverture de leçon.'),
  proposal(exercises[5] as ExerciseOut, 0.74, 'Comparaison, souvent fragile dans cette classe.'),
  proposal(exercises[3] as ExerciseOut, 0.66, 'Réponse libre : trace écrite du raisonnement.'),
];

export const sheet: SheetOut = {
  id: id(600),
  class_id: id(20),
  subject_id: id(10),
  chapter_id: id(300),
  // Derived from the items, not stored — the two exercises tagged MSN 32/33.
  competency_ids: [id(200), id(201)],
  chapter_ids: [id(300)],
  // A common sheet answers nothing; only a differentiated batch has a lineage.
  source_sheet_ids: [],
  // One pile, signed off — so the theme page can show "Corrigée".
  scans: [
    {
      id: id(800),
      status: 'confirmed',
      revised: false,
      confirmed_at: '2026-03-16T10:00:00+01:00',
      reopened_at: null,
      created_at: '2026-03-16T09:30:00+01:00',
    },
  ],
  title: 'Fractions — révision avant le test',
  target: 'class',
  language: 'fr',
  intent: 'révision fractions avant le test',
  layout_version: 'v1',
  default_points_correct: 1,
  default_points_penalty: 0.25,
  // Item 3 is worth more than the rest, so the builder's "modifié" summary and
  // the printed "(3 pts)" both have something to show in the mock.
  items: [exercises[0], exercises[2], exercises[4], exercises[1], exercises[5]].map((ex, index) => ({
    id: id(610 + index),
    position: index,
    statement_override: null,
    answer_box_lines: null,
    answer_box_fill: null,
    expected_answer: null,
    points_correct: index === 2 ? 3 : null,
    points_penalty: index === 2 ? 0 : null,
    exercise: ex as ExerciseOut,
  })),
  instances: students.slice(0, 3).map((student, index) => ({
    id: id(630 + index),
    student_id: student.id,
    student_uid: student.uid,
    page_count: 1,
    group_label: null,
    has_feedback: false,
    points_earned: index === 0 ? 5.75 : null,
    points_possible: 7,
  })),
  blank_pdf_url: null,
  answer_key_pdf_url: null,
  feedback_pdf_url: null,
  derived_from_id: null,
  rendered_at: null,
  created_at: '2026-03-12T14:30:00+01:00',
};

const detections: DetectionOut[] = [
  { index: 0, detected: 0, confidence: 0.97, outcome: 'detected' as const, tf: false, open: false },
  { index: 1, detected: 2, confidence: 0.41, outcome: 'low_confidence' as const, tf: false, open: false },
  { index: 2, detected: null, confidence: 0.12, outcome: 'blank' as const, tf: false, open: false },
  { index: 3, detected: 3, confidence: 0.93, outcome: 'detected' as const, tf: false, open: false },
  { index: 4, detected: 1, confidence: 0.55, outcome: 'multiple' as const, tf: true, open: false },
  { index: 5, detected: null, confidence: 0.91, outcome: 'detected' as const, tf: false, open: true },
].map((raw) => ({
  id: id(700 + raw.index),
  item_index: raw.index,
  number: raw.index + 1,
  sheet_item_id: id(610 + raw.index),
  exercise_id: id(500 + raw.index),
  detected_index: raw.detected,
  detected_bool: raw.tf && raw.detected !== null ? raw.detected === 0 : null,
  confidence: raw.confidence,
  outcome: raw.outcome,
  fill_ratios: [0.08, 0.72, 0.11, 0.05],
  bubble_boxes: [
    { u: 0.1, v: 0.18 + raw.index * 0.107, w: 0.05, h: 0.028 },
    { u: 0.185, v: 0.18 + raw.index * 0.107, w: 0.05, h: 0.028 },
    { u: 0.27, v: 0.18 + raw.index * 0.107, w: 0.05, h: 0.028 },
    { u: 0.355, v: 0.18 + raw.index * 0.107, w: 0.05, h: 0.028 },
  ],
  corrected_at: null,
  machine_index: raw.detected,
  machine_outcome: raw.outcome,
  machine_confidence: raw.confidence,
  statement: raw.open
    ? 'Calcule 3/4 + 1/8 et donne le résultat sous forme de fraction irréductible.'
    : `Question ${raw.index + 1} — une fraction a simplifier`,
  options: raw.tf || raw.open ? null : ['1/2', '2/4', '3/6', '4/8'],
  option_letters: raw.open ? null : raw.tf ? 'VF' : 'ABCD',
  exercise_type: raw.open
    ? ('open' as const)
    : raw.tf
      ? ('true_false' as const)
      : ('mcq' as const),
  ai_generated: false,
  answer_index: raw.open ? null : raw.tf ? 0 : 1,
  // The written answer: the box cut from the page and what the model read.
  crop_url: raw.open ? '/mock/answer-box.svg' : null,
  transcription: raw.open ? '3/4 + 1/8 = 6/8 + 1/8 = 7/8' : null,
  verdict_correct: raw.open ? true : null,
  machine_transcription: raw.open ? '3/4 + 1/8 = 6/8 + 1/8 = 7/8' : null,
  machine_verdict_correct: raw.open ? true : null,
  vision_model: raw.open ? 'claude-sonnet-5' : null,
  reference_answer: null,
  answer_text: raw.open ? '7/8' : null,
}));

/** Every page the mock scan carries, minus the bits each one overrides. */
const pageDefaults = {
  wrong_class: false,
  discarded: false,
  page_in_copy: 0,
  registration_error: null,
} as const;

export const scan: ScanOut = {
  id: id(800),
  sheet_id: id(600),
  original_filename: 'copies-7b-fractions.pdf',
  status: 'needs_review',
  error: null,
  job_id: null,
  revised: false,
  reopened_at: null,
  confirmed_at: null,
  created_at: '2026-03-16T07:40:00+01:00',
  pages: [
    {
      id: id(810),
      page_index: 0,
      image_url: '/mock/scan-page.svg',
      registered: true,
      detected_uid: '7B_04',
      uid_confidence: 0.99,
      student_id: id(103),
      sheet_instance_id: id(630),
      ...pageDefaults,
      detections,
    },
    {
      id: id(811),
      page_index: 1,
      image_url: '/mock/scan-page.svg',
      registered: true,
      detected_uid: null,
      uid_confidence: 0.22,
      student_id: null,
      sheet_instance_id: null,
      ...pageDefaults,
      page_in_copy: null,
      detections: detections.map((d, i) => ({ ...d, id: id(750 + i) })),
    },
    {
      // A cover sheet the teacher photographed by accident: it belongs to
      // nobody, and it must not hold the other copies hostage.
      id: id(812),
      page_index: 2,
      image_url: '/mock/scan-page.svg',
      registered: false,
      detected_uid: null,
      uid_confidence: 0,
      student_id: null,
      sheet_instance_id: null,
      ...pageDefaults,
      page_in_copy: null,
      registration_error: 'found 0 fiducial candidates, need 4',
      detections: [],
    },
  ],
};

export function studentProfile(studentId: string): StudentProfileOut {
  const student = students.find((s) => s.id === studentId) ?? (students[0] as StudentOut);
  const studentIndex = students.indexOf(student);
  const entries = competencies.map((competency, ci) => {
    const score = pseudoScore(studentIndex, ci);
    return {
      competency,
      score,
      band: bandOf(score),
      attempts_count: ((studentIndex + ci) % 6) + 1,
      provisional: ((studentIndex + ci) % 6) + 1 < 3,
      days_until_review: score >= 0.75 ? ((studentIndex + ci) % 9) + 1 : 0,
      history: [0, 7, 14, 21].map((offset) => ({
        at: new Date(Date.parse('2026-02-16T09:00:00Z') + offset * 86_400_000).toISOString(),
        score: Math.round(Math.max(0.2, Math.min(0.98, score - 0.12 + offset * 0.006)) * 100) / 100,
        band: bandOf(score),
      })),
    };
  });
  const sorted = [...entries].sort((a, b) => b.score - a.score);
  return {
    student,
    overall_score:
      Math.round((entries.reduce((sum, e) => sum + e.score, 0) / entries.length) * 100) / 100,
    strengths: sorted.slice(0, 3),
    gaps: sorted.slice(-3).reverse(),
    all_competencies: entries,
    sheets_taken: sheetsTaken.length,
    sheets: sheetsTaken,
  };
}

/** The sheets behind the profile's history list. */
const sheetsTaken: SheetTakenOut[] = [
  {
    sheet_id: id(600),
    title: 'Fractions — controle 1',
    answered_at: '2026-03-16T09:10:00+01:00',
    attempts_count: 8,
    correct_count: 6,
    scan_id: id(800),
    chapter_id: id(300),
    // Complete coverage, so the band carries no ratio: "2 sur 2" says nothing
    // the band does not (DC-content-07).
    mastery: {
      score: 0.78,
      band: 'ok',
      attempts_count: 8,
      provisional: false,
      assessed_count: 2,
      child_count: 2,
      weakest_band: 'ok',
      days_until_review: 4,
      last_attempt_at: '2026-03-16T09:10:00+01:00',
    },
  },
  {
    sheet_id: id(601),
    title: 'Proportionnalite — exercices',
    answered_at: '2026-03-02T09:10:00+01:00',
    attempts_count: 10,
    correct_count: 5,
    scan_id: null,
    chapter_id: id(301),
    // Partial: one of this sheet's two competencies was never examined, and
    // that is exactly when the coverage has to be shown.
    mastery: {
      score: 0.44,
      band: 'fading',
      attempts_count: 10,
      provisional: false,
      assessed_count: 1,
      child_count: 2,
      weakest_band: 'fading',
      days_until_review: 0,
      last_attempt_at: '2026-03-02T09:10:00+01:00',
    },
  },
];

/** Points per pupil and per sheet, for `/results`.

Deterministic like everything else here: a pupil's ratio is derived from their
index rather than randomised, so the screenshot baselines do not move. Two
pupils are left `null` on the second sheet on purpose — an ungraded copy is a
dash, never a zero (D50), and a fixture that grades everybody would let that
regression through unnoticed. */
export function classPoints(classId: string): ClassPointsOut {
  const sheetsOut = [
    { sheet_id: id(600), sheet_title: 'Fractions — controle 1', possible: 8 },
    { sheet_id: id(601), sheet_title: 'Proportionnalite — exercices', possible: 10 },
  ].map((sheet, sheetIndex) => {
    const perStudent = students.map((student, index) => {
      const ungraded = sheetIndex === 1 && index % 7 === 3;
      return {
        student_id: student.id,
        points_earned: ungraded ? null : ((index * 3 + sheetIndex * 2) % (sheet.possible + 1)),
        points_possible: sheet.possible,
      };
    });
    const graded = perStudent.filter((p) => p.points_earned !== null);
    return {
      sheet_id: sheet.sheet_id,
      sheet_title: sheet.sheet_title,
      average_ratio: graded.length
        ? graded.reduce((sum, p) => sum + (p.points_earned ?? 0) / p.points_possible, 0) /
          graded.length
        : null,
      students: perStudent,
    };
  });

  return {
    class_id: classId,
    students: students.map((student) => {
      const mine = sheetsOut.flatMap((s) =>
        s.students.filter((p) => p.student_id === student.id),
      );
      const graded = mine.filter((p) => p.points_earned !== null);
      return {
        student_id: student.id,
        points_earned: graded.length
          ? graded.reduce((sum, p) => sum + (p.points_earned ?? 0), 0)
          : null,
        points_possible: mine.reduce((sum, p) => sum + p.points_possible, 0),
      };
    }),
    sheets: sheetsOut,
  };
}

/** One sheet's band per pupil, plus the class roll-up. Derived from the same
two competencies the sheet's items carry, so the fixture cannot claim a
coverage the sheet does not have. */
export function sheetMastery(sheetId: string): SheetMasteryOut {
  const covered = [id(200), id(201)];
  const bands: MasteryBandKey[] = ['solid', 'ok', 'weak', 'fading', 'none'];
  return {
    sheet_id: sheetId,
    competency_ids: covered,
    students: students.map((student, index) => ({
      student_id: student.id,
      mastery: {
        score: 0.9 - (index % 5) * 0.12,
        band: bands[index % 5] as MasteryBandKey,
        attempts_count: 8,
        provisional: false,
        assessed_count: index % 4 === 0 ? 1 : 2,
        child_count: 2,
        weakest_band: bands[index % 5] as MasteryBandKey,
        days_until_review: index % 5,
        last_attempt_at: NOW,
      },
    })),
    overall: {
      score: 0.66,
      band: 'weak',
      attempts_count: 144,
      provisional: false,
      assessed_count: 2,
      child_count: 2,
      weakest_band: 'fading',
      days_until_review: 1,
      last_attempt_at: NOW,
    },
    computed_at: NOW,
  };
}

/** The drill-down behind one matrix cell. */
export function competencyAttempts(
  studentId: string,
  competencyId: string,
): CompetencyAttemptsOut {
  const student = students.find((s) => s.id === studentId) ?? (students[0] as StudentOut);
  const competency =
    competencies.find((c) => c.id === competencyId) ?? (competencies[0] as CompetencyOut);
  const score = pseudoScore(students.indexOf(student), competencies.indexOf(competency));
  const attempts = [0, 6, 13, 20].map((offset, index) => ({
    id: id(900 + index),
    exercise_id: id(500 + index),
    statement:
      index === 0
        ? 'Simplifie la fraction 12/18.'
        : `Calcule ${index + 1}/4 + 1/8 et donne le resultat simplifie.`,
    origin: index === 3 ? ('ai_generated' as const) : ('textbook' as const),
    correct: index !== 1,
    difficulty: (index % 5) + 1,
    answered_at: new Date(
      Date.parse('2026-03-16T09:10:00Z') - offset * 86_400_000,
    ).toISOString(),
    sheet_id: id(600),
    sheet_title: 'Fractions — controle 1',
    scan_id: index < 2 ? id(800) : null,
    corrected: index === 1,
  }));
  return {
    student,
    competency,
    score,
    band: bandOf(score),
    provisional: false,
    days_until_review: score >= 0.75 ? 5 : 0,
    attempts,
  };
}

/** A fortnight of a real teaching cycle, newest first. */
export const timeline: TimelineOut = {
  total: 6,
  offset: 0,
  limit: 20,
  facets: {
    by_kind: {
      source_imported: 1,
      sheet_created: 1,
      sheet_printed: 1,
      scan_confirmed: 1,
      adaptive_exported: 1,
      feedback_approved: 1,
    },
  },
  items: [
    {
      id: id(900),
      kind: 'feedback_approved',
      occurred_at: '2026-09-05T16:20:00Z',
      subject_type: 'sheet',
      subject_id: sheet.id,
      title: sheet.title,
      class_id: classes[0].id,
      class_code: classes[0].code,
      subject_area_id: subjects[0].id,
      detail: { notes: 3 },
      resolved: true,
    },
    {
      id: id(901),
      kind: 'adaptive_exported',
      occurred_at: '2026-09-05T16:05:00Z',
      subject_type: 'sheet',
      subject_id: sheet.id,
      title: 'Fractions — fiches adaptées',
      class_id: classes[0].id,
      class_code: classes[0].code,
      subject_area_id: subjects[0].id,
      detail: { groups: 4, copies: 18 },
      resolved: true,
    },
    {
      id: id(902),
      kind: 'scan_confirmed',
      occurred_at: '2026-09-04T19:40:00Z',
      subject_type: 'scan',
      subject_id: id(500),
      title: sheet.title,
      class_id: classes[0].id,
      class_code: classes[0].code,
      subject_area_id: subjects[0].id,
      detail: { attempts: 90, students: 18 },
      resolved: true,
    },
    {
      id: id(903),
      kind: 'sheet_printed',
      occurred_at: '2026-09-02T07:15:00Z',
      subject_type: 'sheet',
      subject_id: sheet.id,
      title: sheet.title,
      class_id: classes[0].id,
      class_code: classes[0].code,
      subject_area_id: subjects[0].id,
      detail: { copies: 18 },
      resolved: true,
    },
    {
      id: id(904),
      kind: 'sheet_created',
      occurred_at: '2026-09-01T14:00:00Z',
      subject_type: 'sheet',
      subject_id: sheet.id,
      title: sheet.title,
      class_id: classes[0].id,
      class_code: classes[0].code,
      subject_area_id: subjects[0].id,
      detail: { items: 5, copies: 18 },
      resolved: true,
    },
    {
      id: id(905),
      kind: 'source_imported',
      occurred_at: '2026-08-28T09:30:00Z',
      subject_type: 'source',
      subject_id: id(700),
      // Staffroom work: it belongs to no class, so every teacher sees it.
      title: 'mathematiques-9e.pdf',
      class_id: null,
      class_code: null,
      subject_area_id: subjects[0].id,
      detail: { bytes: 4200000 },
      resolved: true,
    },
  ],
};

export const adaptive: AdaptiveProposeResponse = {
  language: 'fr',
  grouped_by_model: false,
  generated_count: 2,
  needs_approval: true,
  group: null,
  groups: [],
  // One student's generation came back short. The screen has to show this, so
  // the fixture has to carry it.
  failures: [
    {
      student_id: (students[3] as { id: string }).id,
      student_uid: (students[3] as { uid: string }).uid,
      reason: 'incomplete',
      requested: 2,
      produced: 0,
      detail: 'the model returned fewer exercises than were asked for',
    },
  ],
  plans: students.slice(0, 4).map((student, index) => ({
    student_id: student.id,
    student_uid: student.uid,
    targeted_competency_ids: [id(200 + (index % 3)), id(200 + ((index + 2) % 5))],
    // The mock exercises the interesting path: a source sheet was corrected, and
    // one copy in four came back only partly read.
    targeting_basis: 'source_sheet' as const,
    evidence_partial: index === 3,
    retrieved: [
      proposal(exercises[index % exercises.length] as ExerciseOut, 0.86, 'Cible la lacune principale.'),
      proposal(exercises[(index + 2) % exercises.length] as ExerciseOut, 0.79, 'Consolide un acquis fragile.'),
    ],
    generated:
      index < 2
        ? [
            proposal(
              { ...aiExercise, id: id(520 + index) },
              0.83,
              'Aucun exercice du manuel ne couvrait cette lacune à ce niveau.',
            ),
          ]
        : [],
  })),
};

export { NOW, id };

/**
 * A stand-in for the print document `POST /sheets/preview` returns.
 *
 * The real endpoint renders the same Jinja templates and the same millimetre
 * geometry out of `alppy/sheets/layout.py` that the PDF is made from — none of
 * which exists in the browser. So this draws a recognisable A4 page carrying the
 * one thing the builder actually reads back from the preview: how many pages the
 * chosen exercises occupy, and in what order they print.
 *
 * It is deliberately NOT a faithful copy of the sheet. Making it one would put a
 * second implementation of the layout in the repo, which is the exact drift
 * `layout.py` exists to prevent — the mock is for screenshot and e2e runs with no
 * backend, and the real preview is what a teacher checks before printing.
 */
export function draftPreviewHtml(draft: {
  title: string;
  items: { exercise_id: string; position: number; statement_override?: string | null }[];
}): string {
  const byId = new Map(exercises.map((e) => [e.id, e]));
  const ordered = [...draft.items].sort((a, b) => a.position - b.position);
  const rows = ordered
    .map((item, index) => {
      const found = byId.get(item.exercise_id);
      const text = item.statement_override ?? found?.statement ?? '—';
      return `<li><b>${index + 1}.</b> ${escapeHtml(text)}</li>`;
    })
    .join('');
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>${escapeHtml(draft.title || 'Feuille')}</title>
<style>
  body { margin:0; font-family: system-ui, sans-serif; background:#fff; color:#000; }
  .print-page { width:210mm; min-height:297mm; padding:14mm; box-sizing:border-box; position:relative; }
  [data-fiducial] { position:absolute; width:8mm; height:8mm; border:2px solid #000; }
  ol { padding-left:1.2em; font-size:11pt; line-height:1.6; }
  h1 { font-size:14pt; margin:0 0 2mm; }
  .meta { font-size:9pt; color:#333; margin:0 0 6mm; }
</style></head><body>
<div class="print-page" data-mock-preview="true">
  <span data-fiducial style="left:14mm;top:14mm"></span>
  <span data-fiducial style="right:14mm;top:14mm"></span>
  <span data-fiducial style="left:14mm;bottom:14mm"></span>
  <span data-fiducial style="right:14mm;bottom:14mm"></span>
  <h1>${escapeHtml(draft.title || 'Feuille')}</h1>
  <p class="meta">7B · Mathématiques · aperçu</p>
  <ol>${rows}</ol>
</div>
</body></html>`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Exercises for a chapter the teacher just asked Alppy to read.
 *
 * Enough of them that the picker's paging, facet counts and page-group headers
 * have something to do — a chapter that came back with three rows would let a
 * broken paginator pass.
 */
export function exercisesForSection(
  section: SourceSectionOut,
  offset: number,
): ExerciseOut[] {
  const span = Math.max(1, section.page_to - section.page_from);
  return Array.from({ length: 24 }, (_, i) => {
    const kind: ExerciseType = i % 3 === 0 ? 'mcq' : i % 3 === 1 ? 'true_false' : 'open';
    return {
      ...exercise(offset + i),
      id: id(1200 + offset + i),
      type: kind,
      statement: `${section.title} — exercice ${i + 1}.`,
      options: kind === 'mcq' ? ['A', 'B', 'C', 'D'] : null,
      answer_index: kind === 'mcq' ? i % 4 : null,
      answer_bool: kind === 'true_false' ? i % 2 === 0 : null,
      answer_text: kind === 'open' ? 'Réponse libre.' : null,
      source_section_id: section.id,
      source_page: section.page_from + (i % span),
    };
  });
}

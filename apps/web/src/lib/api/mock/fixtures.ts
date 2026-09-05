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
  CompetencyOut,
  DetectionOut,
  ExerciseOut,
  ExerciseProposal,
  HomeOut,
  MasteryMatrixOut,
  ScanOut,
  SheetOut,
  SourceOut,
  StudentOut,
  StudentProfileOut,
  SubjectOut,
  TeacherOut,
} from '../types';

const NOW = '2026-03-16T08:00:00+01:00';

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

export const teacher: TeacherOut = {
  id: id(1),
  email: 'claire.fontaine@example.ch',
  first_name: 'Claire',
  last_name: 'Fontaine',
  school_id: id(2),
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

export const students: StudentOut[] = NAMES.map(([first, last], index) => ({
  id: id(100 + index),
  uid: `7B_${String(index + 1).padStart(2, '0')}`,
  number: index + 1,
  first_name: first,
  last_name: last ?? '',
}));

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
}));

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
      // Two students × one competency were never assessed: `none` is a real band.
      if ((si + ci) % 17 === 0) return [];
      const score = pseudoScore(si, ci);
      return [
        {
          student_id: student.id,
          competency_id: competency.id,
          score,
          band: bandOf(score),
          attempts_count: ((si + ci) % 6) + 1,
          provisional: ((si + ci) % 6) + 1 < 3,
          days_until_review: score >= 0.75 ? ((si * ci) % 9) + 1 : 0,
          last_attempt_at: '2026-03-09T10:15:00+01:00',
        },
      ];
    }),
  ),
  computed_at: NOW,
};

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
    filename: 'mathematiques-9e-cycle3.pdf',
    content_type: 'application/pdf',
    size_bytes: 18_432_100,
    language: 'fr',
    page_count: 244,
    status: 'succeeded',
    error: null,
    exercise_count: 312,
    created_at: '2026-02-28T09:12:00+01:00',
  },
  {
    id: id(401),
    filename: 'cahier-exercices-fractions.pdf',
    content_type: 'application/pdf',
    size_bytes: 4_120_400,
    language: 'fr',
    page_count: 48,
    status: 'running',
    error: null,
    exercise_count: 0,
    created_at: '2026-03-16T07:55:00+01:00',
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
    source_page: 84 + index,
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
  title: 'Fractions — révision avant le test',
  target: 'class',
  language: 'fr',
  intent: 'révision fractions avant le test',
  layout_version: 'v1',
  items: [exercises[0], exercises[2], exercises[4], exercises[1], exercises[5]].map((ex, index) => ({
    id: id(610 + index),
    position: index,
    statement_override: null,
    exercise: ex as ExerciseOut,
  })),
  instances: students.slice(0, 3).map((student, index) => ({
    id: id(630 + index),
    student_id: student.id,
    student_uid: student.uid,
    page_count: 1,
  })),
  blank_pdf_url: null,
  answer_key_pdf_url: null,
  rendered_at: null,
  created_at: '2026-03-12T14:30:00+01:00',
};

const detections: DetectionOut[] = [
  { index: 0, detected: 0, confidence: 0.97, outcome: 'detected' as const },
  { index: 1, detected: 2, confidence: 0.41, outcome: 'low_confidence' as const },
  { index: 2, detected: null, confidence: 0.12, outcome: 'blank' as const },
  { index: 3, detected: 3, confidence: 0.93, outcome: 'detected' as const },
  { index: 4, detected: 1, confidence: 0.55, outcome: 'multiple' as const },
  { index: 5, detected: null, confidence: 0, outcome: 'not_gradeable' as const },
].map((raw) => ({
  id: id(700 + raw.index),
  item_index: raw.index,
  sheet_item_id: id(610 + raw.index),
  detected_index: raw.detected,
  detected_bool: null,
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
}));

export const scan: ScanOut = {
  id: id(800),
  sheet_id: id(600),
  original_filename: 'copies-7b-fractions.pdf',
  status: 'needs_review',
  error: null,
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
      detections: detections.map((d, i) => ({ ...d, id: id(750 + i) })),
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
    sheets_taken: 4,
  };
}

export const adaptive: AdaptiveProposeResponse = {
  language: 'fr',
  generated_count: 2,
  needs_approval: true,
  plans: students.slice(0, 4).map((student, index) => ({
    student_id: student.id,
    student_uid: student.uid,
    targeted_competency_ids: [id(200 + (index % 3)), id(200 + ((index + 2) % 5))],
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

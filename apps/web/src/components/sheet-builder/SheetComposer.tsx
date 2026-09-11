'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  EmptyState,
  IconChevronDown,
  IconChevronRight,
  IconChevronUp,
  IconClose,
  IconDrag,
  IconEdit,
  IconButton,
  IconPlus,
  IconSheet,
  IconWarning,
  Field,
  Input,
  Panel,
  Select,
  Textarea,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { ITEMS_PER_PAGE } from '@/lib/optionLetters';
import { useFormatters } from '@/lib/format';
import { TYPE_VARIANT } from './ExerciseRow';
import type { AnswerBoxFill, AnswerBoxLines, Uuid } from '@/lib/api/types';
import {
  ANSWER_BOX_FILLS,
  ANSWER_BOX_LINES,
  DEFAULT_POINTS_CORRECT,
  MAX_ANSWER_BOX_LINES,
  MAX_ITEM_POINTS,
  MAX_SHEET_ITEMS,
  PENALTY_PRESETS,
  POINTS_PRESETS,
  answerBoxOf,
  baremeOf,
  clampAnswerBoxLines,
  expectedAnswerOf,
  hasOwnBareme,
  parseDecimalInput,
  type AnswerBox,
  type Bareme,
  type DraftItem,
  type DraftSheet,
} from './useDraftSheet';

interface Props {
  draft: DraftSheet;
  onAdd: () => void;
  /** Rendered under the list: the generate action. */
  footer?: React.ReactNode;
  previewOpen?: boolean;
  onTogglePreview?: () => void;
}

/**
 * What is actually going on the paper, in the order it will print.
 *
 * Reordering offers two affordances on purpose. The arrows are the accessible
 * path — keyboard-reachable, 44 px, and the only one that works on a phone
 * with assistive touch — and the drag handle is the fast one for a mouse. The
 * handle is HTML5 drag-and-drop rather than a library: the Worker bundle has a
 * 3 MiB ceiling (decisions-log D25) and a sortable list is not worth 40 kB of it.
 *
 * The header is the page budget. The preview is closed by default, so this
 * line is the only thing standing between a teacher and forty exercises on a
 * grid that holds sixteen a page; the server preview stays the authority on
 * the real count, because statement height also decides it.
 */
export function SheetComposer({ draft, onAdd, footer, previewOpen, onTogglePreview }: Props) {
  const t = useTranslations('builder');
  const ts = useTranslations('sheets');
  const tc = useTranslations('common');
  const tx = useTranslations('exercise');
  const ta = useTranslations('adaptive');

  const [editing, setEditing] = useState<string | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const overflows = draft.count > ITEMS_PER_PAGE;

  return (
    <Card className="flex flex-col gap-3" data-composer>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-h3">{t('onSheet')}</h2>
          {draft.count > 0 ? (
            <p className="text-body-s text-ink-500" data-numeric>
              {t('exerciseCount', { count: draft.count })} ·{' '}
              {t('pagesA4', { count: draft.minPages })}
              {draft.isFull ? (
                <span className="ml-1 text-warn-600">
                  ({t('itemsOfMax', { count: draft.count, max: MAX_SHEET_ITEMS })})
                </span>
              ) : null}
            </p>
          ) : null}
        </div>
        {onTogglePreview ? (
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={<IconSheet />}
            aria-pressed={previewOpen}
            onClick={onTogglePreview}
          >
            {previewOpen ? t('hidePreview') : t('showPreview')}
          </Button>
        ) : null}
      </div>

      {overflows ? (
        <p
          className="flex items-start gap-2 rounded-sm bg-warn-100 p-2 text-body-s text-warn-600"
          role="status"
        >
          <IconWarning size={18} className="mt-0.5 shrink-0" aria-hidden />
          {t('overflowHelp', { count: draft.minPages })}
        </p>
      ) : null}

      {draft.count > 0 ? <BaremePanel draft={draft} /> : null}

      {draft.count === 0 ? (
        <EmptyState
          illustration={<IconSheet size={48} aria-hidden />}
          title={t('emptySheetTitle')}
          description={t('emptySheetBody')}
          size="sm"
        />
      ) : (
        <ol className="flex list-none flex-col gap-2 p-0">
          {draft.items.map((item, index) => {
            const { exercise } = item;
            const isEditing = editing === exercise.id;
            return (
              <li
                key={exercise.id}
                draggable={!isEditing}
                onDragStart={() => setDragging(index)}
                onDragEnd={() => setDragging(null)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  if (dragging !== null) draft.reorder(dragging, index);
                  setDragging(null);
                }}
                data-dragging={dragging === index || undefined}
              >
                <Panel
                  className={
                    isEditing
                      ? 'border-primary-500 shadow-[0_0_0_4px_var(--c-primary-100)]'
                      : dragging === index
                        ? 'opacity-60'
                        : undefined
                  }
                >
                  {/* One line of metadata with the actions at its end; the
                      statement takes the full width beneath it, because it is
                      what gets printed and cannot shrink to fit. */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="shrink-0 cursor-grab text-ink-300"
                      aria-hidden
                      title={t('reorderHelp')}
                    >
                      <IconDrag size={18} />
                    </span>
                    <span
                      className="mono w-5 shrink-0 text-body-s font-bold text-ink-700"
                      data-numeric
                    >
                      {index + 1}
                    </span>
                    <div className="flex min-w-0 flex-grow flex-wrap items-center gap-1.5">
                      <Badge variant={TYPE_VARIANT[exercise.type]}>
                        {tx(`type.${exercise.type}`)}
                      </Badge>
                      {exercise.source_page ? (
                        <span className="text-body-s text-ink-500">
                          {t('pageLabel', { page: exercise.source_page })}
                        </span>
                      ) : null}
                      {/* Teacher-written items get a neutral chip. The
                          mandarin means exactly one thing — a model wrote
                          this — and spending it here would cost it that. */}
                      {exercise.origin === 'teacher' ? (
                        <Badge variant="neutral">{t('writtenByYou')}</Badge>
                      ) : null}
                      {exercise.origin === 'ai_generated' ? (
                        <AiBadge label={ta('aiBadge')} />
                      ) : null}
                      {item.override ? <Badge variant="neutral">{ts('edited')}</Badge> : null}
                    </div>
                    <div className="-mr-2 ml-auto flex shrink-0 items-center">
                      <IconButton
                        label={ts('editStatement')}
                        icon={<IconEdit />}
                        variant="ghost"
                        size="sm"
                        aria-pressed={isEditing}
                        onClick={() =>
                          setEditing((current) => (current === exercise.id ? null : exercise.id))
                        }
                      />
                      <IconButton
                        label={ts('moveUp')}
                        icon={<IconChevronUp />}
                        variant="ghost"
                        size="sm"
                        disabled={index === 0}
                        onClick={() => draft.move(index, -1)}
                      />
                      <IconButton
                        label={ts('moveDown')}
                        icon={<IconChevronDown />}
                        variant="ghost"
                        size="sm"
                        disabled={index === draft.count - 1}
                        onClick={() => draft.move(index, 1)}
                      />
                      <IconButton
                        label={t('remove')}
                        icon={<IconClose />}
                        variant="ghost"
                        size="sm"
                        onClick={() => draft.remove(exercise.id)}
                      />
                    </div>
                  </div>

                  {isEditing ? (
                    <div className="mt-2 pl-7">
                      <Textarea
                        aria-label={ts('editStatement')}
                        value={item.override ?? exercise.statement}
                        onChange={(event) => {
                          // Read the value before the updater runs:
                          // `currentTarget` is null by the time React calls
                          // a lazy updater.
                          const next = event.currentTarget.value;
                          draft.setOverride(exercise.id, next);
                        }}
                        rows={3}
                      />
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button size="sm" onClick={() => setEditing(null)}>
                          {tc('done')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            draft.setOverride(exercise.id, undefined);
                            setEditing(null);
                          }}
                        >
                          {ts('resetStatement')}
                        </Button>
                      </div>
                      <p className="mt-2 text-body-s text-ink-500">{t('overrideHelp')}</p>
                    </div>
                  ) : (
                    <p className="mt-1 pl-7" data-student-facing>
                      {item.override ?? exercise.statement}
                    </p>
                  )}

                  <ItemSettings item={item} draft={draft} />
                </Panel>
              </li>
            );
          })}
        </ol>
      )}

      <Button
        variant="secondary"
        block
        leadingIcon={<IconPlus />}
        onClick={onAdd}
        disabled={draft.isFull}
        className="border-2 border-dashed border-line-strong text-primary-700 shadow-none"
      >
        {t('addExercise')}
      </Button>

      {footer}
    </Card>
  );
}

/**
 * The barème the whole sheet grades by.
 *
 * A Panel, not a Card: it is a subdivision of the composer the teacher is
 * already inside, not a separate object. It sits above the list because it is
 * the value every item below inherits — a teacher sets it once and most sheets
 * never touch it again.
 */
/**
 * A barème, as text.
 *
 * Two fraction digits, not `fmt.number`'s default of one: a quarter-point
 * penalty is a real barème and `0.3` is not it.
 *
 * Every points number on this screen goes through here, because the catalogue's
 * own `{points, number}` formatted with next-intl's locale (`fr`, a comma) while
 * `lib/format.ts` formats with `fr-CH` (a period, which is correct for the
 * locale and what §10.1 of the audit defends). The two sat inches apart in this
 * panel — `Total : 2,5 points` above a field reading `2.5` — and on the student
 * sheet they shared a line as `3.25 / 4,5 pts`. One authority, one separator.
 */
function usePointsText(): (value: number) => string {
  const fmt = useFormatters();
  return useCallback((value: number) => fmt.number(value, 2), [fmt]);
}

function BaremePanel({ draft }: { draft: DraftSheet }) {
  const t = useTranslations('builder');
  const points = usePointsText();
  return (
    <Panel sunken className="flex flex-col gap-2" data-bareme>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-label uppercase text-ink-700">{t('baremeTitle')}</span>
        <span className="text-body-s text-ink-500" data-numeric>
          {t('baremeTotal', { points: points(draft.totalPoints) })}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={t('baremePoints')}>
          <PointsSelect
            value={draft.bareme.correct}
            presets={POINTS_PRESETS}
            label={(v) => t('pointsOption', { points: points(v) })}
            onChange={(correct) => draft.setBareme({ correct })}
          />
        </Field>
        <Field label={t('baremePenalty')}>
          <PointsSelect
            value={draft.bareme.penalty}
            presets={PENALTY_PRESETS}
            emptyMeans={0}
            label={(v) => (v === 0 ? t('penaltyNone') : t('penaltyOption', { points: points(v) }))}
            onChange={(penalty) => draft.setBareme({ penalty })}
          />
        </Field>
      </div>
      <p className="text-body-s text-ink-500">{t('baremeHelp')}</p>
    </Panel>
  );
}

const CUSTOM_POINTS = 'custom';

/**
 * A points value: the shortcuts a teacher reaches for, plus "custom" for
 * anything else. Same shape as the box-height control next to it — presets in
 * a select, a number field when none of them fits.
 */
/**
 * A barème: pick a preset, or type one.
 *
 * Exported for its own test. The bug this control carried lived in the
 * round-trip between the text a teacher types and the number the draft holds,
 * which is reachable only by driving the real field with real keystrokes — a
 * test of the parse alone would have passed against the broken version.
 */
export function PointsSelect({
  value,
  presets,
  label,
  onChange,
  placeholder,
  emptyMeans = DEFAULT_POINTS_CORRECT,
}: {
  value: number | undefined;
  presets: readonly number[];
  label: (value: number) => string;
  onChange: (value: number | undefined) => void;
  /** Shown as the first option when the value is undefined — "follow the
   *  sheet". Absent on the sheet's own barème, which always has a value. */
  placeholder?: string;
  /**
   * What clearing the custom field means. Per field, not per control: an empty
   * PENALTY field means "no penalty", and inheriting the points default here
   * would have a teacher who deleted the contents of a penalty box walk away
   * having set a penalty of one point. A single shared fallback cannot make
   * this distinction: it has no idea which field it is serving.
   */
  emptyMeans?: number;
}) {
  const t = useTranslations('builder');
  const points = usePointsText();
  const isPreset = value !== undefined && presets.includes(value);
  const [custom, setCustom] = useState(value !== undefined && !isPreset);
  const showCustom = custom || (value !== undefined && !isPreset);
  return (
    <>
      <Select
        value={value === undefined ? '' : showCustom ? CUSTOM_POINTS : String(value)}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          if (raw === '') {
            setCustom(false);
            onChange(undefined);
            return;
          }
          if (raw === CUSTOM_POINTS) {
            setCustom(true);
            if (value === undefined) onChange(1);
            return;
          }
          setCustom(false);
          onChange(Number(raw));
        }}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {presets.map((preset) => (
          <option key={preset} value={preset}>
            {label(preset)}
          </option>
        ))}
        <option value={CUSTOM_POINTS}>{t('pointsCustom')}</option>
      </Select>
      {showCustom ? (
        <DecimalField
          value={value ?? emptyMeans}
          emptyMeans={emptyMeans}
          ariaLabel={t('pointsCustomLabel', { max: points(MAX_ITEM_POINTS) })}
          onChange={onChange}
        />
      ) : null}
    </>
  );
}

/**
 * A barème a teacher types, as opposed to one they pick.
 *
 * The draft is held as TEXT and parsed only on the way out, because `1.` and
 * `1,` and `` are all states the field passes THROUGH on the way to `1.5` and
 * none of them is a number. The previous version round-tripped every keystroke
 * through `Number(...)` and straight back into `value`, so typing `1.5`
 * produced **5**: the browser's own value sanitisation empties the intermediate
 * `1.`, `Number('')` is `0`, and the next keystroke landed in a field that had
 * been silently reset. A comma failed the same way, one step earlier.
 *
 * `type="text"` with `inputMode="decimal"`, not `type="number"`: a number
 * input's value sanitisation is what discards a comma before any handler can
 * see it, so no parse layered on top could accept one. The cost is the native
 * stepper, which the preset dropdown beside it already replaces.
 */
function DecimalField({
  value,
  emptyMeans,
  ariaLabel,
  onChange,
}: {
  value: number;
  /** What an emptied field means — the caller's call, not this field's. */
  emptyMeans: number;
  ariaLabel: string;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(() => String(value));

  useEffect(() => {
    // Follow the value when something OTHER than this field moved it. Compared
    // against the PARSE rather than the text, so `1,50` is not rewritten to
    // `1.5` under the cursor while the teacher is still typing it.
    if (parseDecimalInput(draft, emptyMeans) !== value) setDraft(String(value));
    // `draft` is deliberately not a dependency: this effect exists to overwrite
    // the draft from outside, and depending on it would fight every keystroke.
  }, [value, emptyMeans]);

  return (
    <Input
      type="text"
      inputMode="decimal"
      numeric
      aria-label={ariaLabel}
      value={draft}
      onChange={(event) => {
        const next = event.currentTarget.value;
        setDraft(next);
        onChange(parseDecimalInput(next, emptyMeans));
      }}
    />
  );
}

/**
 * Everything one item can be configured with, behind a line that summarises it.
 *
 * Every item gets this drawer, because every item has a barème. What is inside
 * depends on the type: a written item also chooses its box and the answer it is
 * judged against, and neither of those means anything on a bubble item — the
 * answer of an MCQ is the bubble.
 *
 * The summary is what a teacher scans a list of twelve items for; the controls
 * are one click further. Twelve open panels is what made this unreadable.
 */
function ItemSettings({ item, draft }: { item: DraftItem; draft: DraftSheet }) {
  const t = useTranslations('builder');
  const points = usePointsText();
  const isOpen = item.exercise.type === 'open';
  const bareme = baremeOf(item, draft.bareme);
  const box = answerBoxOf(item);
  const fillLabel: Record<AnswerBoxFill, string> = {
    lined: t('boxFillLined'),
    grid: t('boxFillGrid'),
    blank: t('boxFillBlank'),
  };
  // The fill is named only when it is not the default: "5 lines, lined" says
  // the same word twice.
  const boxText =
    box.lines === 0
      ? t('boxNone')
      : box.fill === 'lined'
        ? t('boxSummary', { count: box.lines })
        : `${t('boxSummary', { count: box.lines })}, ${fillLabel[box.fill].toLowerCase()}`;

  // The barème leads the summary: it is the one setting every item has, and
  // the one a teacher checks down the whole list.
  const baremeText = [
    t('pointsSummary', { points: points(bareme.correct) }),
    bareme.penalty === 0
      ? t('penaltySummaryNone')
      : t('penaltySummary', { points: points(bareme.penalty) }),
  ].join(' · ');
  const summary = [
    baremeText,
    ...(isOpen
      ? [boxText, expectedAnswerOf(item).trim() ? t('answerSummaryGiven') : t('answerSummaryModel')]
      : []),
  ].join(' · ');

  return (
    <details className="group mt-2 ml-7" data-item-settings>
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-sm text-body-s text-ink-700 hover:text-primary-700 focus-visible:shadow-[0_0_0_4px_var(--c-primary-100)] focus-visible:outline-none [&::-webkit-details-marker]:hidden">
        <IconChevronRight
          size={16}
          className="shrink-0 text-ink-500 transition-transform group-open:rotate-90"
          aria-hidden
        />
        <span>{summary}</span>
        {/* Never colour alone: an item departing from the sheet's barème says
            so in a word, not by weight or tint. */}
        {hasOwnBareme(item) ? <Badge variant="primary">{t('baremeOverridden')}</Badge> : null}
      </summary>
      <div className="flex flex-col gap-2 pb-1">
        <ItemBaremeControl item={item} sheet={draft.bareme} onChange={draft.setItemBareme} />
        {isOpen ? (
          <>
            <AnswerBoxControl
              exerciseId={item.exercise.id}
              box={box}
              onChange={draft.setAnswerBox}
            />
            <ExpectedAnswerControl item={item} onChange={draft.setExpectedAnswer} />
          </>
        ) : null}
      </div>
    </details>
  );
}

/**
 * One item's own barème, when it departs from the sheet's.
 *
 * Both selects lead with "follow the sheet", which is what most items do and
 * what keeps them following the sheet when the teacher changes it later — the
 * value is left unset rather than copied.
 */
function ItemBaremeControl({
  item,
  sheet,
  onChange,
}: {
  item: DraftItem;
  sheet: Bareme;
  onChange: (id: Uuid, patch: Partial<Bareme> | undefined) => void;
}) {
  const t = useTranslations('builder');
  const points = usePointsText();
  return (
    <Panel sunken className="flex flex-col gap-2" data-item-bareme>
      <span className="text-label uppercase text-ink-700">{t('baremeItemTitle')}</span>
      <div className="flex flex-col gap-2">
        <Field label={t('baremePoints')}>
          <PointsSelect
            value={item.points?.correct}
            presets={POINTS_PRESETS}
            placeholder={t('baremeFollowsSheet', { points: points(sheet.correct) })}
            label={(v) => t('pointsOption', { points: points(v) })}
            onChange={(correct) => onChange(item.exercise.id, { correct })}
          />
        </Field>
        <Field label={t('baremePenalty')}>
          <PointsSelect
            value={item.points?.penalty}
            presets={PENALTY_PRESETS}
            emptyMeans={0}
            placeholder={t('baremeFollowsSheet', { points: points(sheet.penalty) })}
            label={(v) => (v === 0 ? t('penaltyNone') : t('penaltyOption', { points: v }))}
            onChange={(penalty) => onChange(item.exercise.id, { penalty })}
          />
        </Field>
      </div>
    </Panel>
  );
}

const CUSTOM_LINES = 'custom';

/**
 * The written-answer box under an open item: its height, and what is printed
 * inside it. Two selects rather than segmented controls — with the preview
 * open this column is too narrow for five buttons in a row without wrapping
 * into a ragged stack. The height select offers the presets and "custom",
 * which opens a number field for any height up to what a page can carry.
 */
function AnswerBoxControl({
  exerciseId,
  box,
  onChange,
}: {
  exerciseId: Uuid;
  box: AnswerBox;
  onChange: (id: Uuid, box: Partial<AnswerBox>) => void;
}) {
  const t = useTranslations('builder');
  const fillLabel: Record<AnswerBoxFill, string> = {
    lined: t('boxFillLined'),
    grid: t('boxFillGrid'),
    blank: t('boxFillBlank'),
  };
  // A height typed by hand is not one of the presets; the select then shows
  // "custom" and the number field carries the value. Choosing "custom" with a
  // preset height keeps the height and only opens the field.
  const isPreset = ANSWER_BOX_LINES.includes(box.lines);
  const [custom, setCustom] = useState(!isPreset);
  const showCustom = custom || !isPreset;
  return (
    <Panel sunken className="flex flex-col gap-2" data-answer-box-control>
      <span className="text-label uppercase text-ink-700">{t('boxTitle')}</span>
      <div className="flex flex-col gap-2">
        <Field label={t('boxLines')}>
          <Select
            value={showCustom ? CUSTOM_LINES : `${box.lines}`}
            onChange={(event) => {
              const value = event.currentTarget.value;
              if (value === CUSTOM_LINES) {
                setCustom(true);
                return;
              }
              setCustom(false);
              onChange(exerciseId, { lines: Number(value) as AnswerBoxLines });
            }}
          >
            {ANSWER_BOX_LINES.map((lines) => (
              <option key={lines} value={lines}>
                {lines === 0 ? t('boxNone') : t('boxLinesOption', { count: lines })}
              </option>
            ))}
            <option value={CUSTOM_LINES}>{t('boxCustom')}</option>
          </Select>
        </Field>
        {showCustom ? (
          <Field label={t('boxCustomLines', { max: MAX_ANSWER_BOX_LINES })}>
            <Input
              type="number"
              inputMode="numeric"
              numeric
              min={1}
              max={MAX_ANSWER_BOX_LINES}
              step={1}
              value={box.lines}
              onChange={(event) =>
                onChange(exerciseId, {
                  lines: clampAnswerBoxLines(event.currentTarget.valueAsNumber),
                })
              }
            />
          </Field>
        ) : null}
        <Field label={t('boxFill')}>
          <Select
            value={box.fill}
            onChange={(event) =>
              onChange(exerciseId, { fill: event.currentTarget.value as AnswerBoxFill })
            }
          >
            {ANSWER_BOX_FILLS.map((fill) => (
              <option key={fill} value={fill}>
                {fillLabel[fill]}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <p className="text-body-s text-ink-500">{t('boxHelp')}</p>
    </Panel>
  );
}

/**
 * The answer the teacher expects for an open item — optional on purpose.
 *
 * With one, the key prints it and the vision grader judges against it and
 * nothing else. Without one, the grader works the answer out itself before
 * judging and shows the teacher what it used. A textbook exercise that already
 * carries an answer shows it here, editable; typing replaces it for this sheet
 * only, the corpus keeps the book's own.
 */
function ExpectedAnswerControl({
  item,
  onChange,
}: {
  item: DraftItem;
  onChange: (id: Uuid, value: string | undefined) => void;
}) {
  const t = useTranslations('builder');
  const value = expectedAnswerOf(item);
  const fromExercise = item.expectedAnswer === undefined && Boolean(item.exercise.answer_text);
  return (
    <Panel sunken className="flex flex-col gap-2" data-expected-answer-control>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-label uppercase text-ink-700">{t('expectedAnswerTitle')}</span>
        <Badge variant="neutral">
          {value.trim() ? t('expectedAnswerGiven') : t('expectedAnswerModel')}
        </Badge>
      </div>
      <Textarea
        aria-label={t('expectedAnswerTitle')}
        value={value}
        placeholder={t('expectedAnswerPlaceholder')}
        rows={2}
        onChange={(event) => {
          const next = event.currentTarget.value;
          onChange(item.exercise.id, next);
        }}
      />
      <p className="text-body-s text-ink-500">
        {fromExercise ? t('expectedAnswerFromBook') : t('expectedAnswerHelp')}
      </p>
    </Panel>
  );
}

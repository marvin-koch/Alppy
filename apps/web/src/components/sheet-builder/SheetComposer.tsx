'use client';

import {
  AiBadge,
  Badge,
  Button,
  Card,
  EmptyState,
  IconChevronDown,
  IconChevronUp,
  IconClose,
  IconDrag,
  IconEdit,
  IconButton,
  IconPlus,
  IconSheet,
  IconWarning,
  Panel,
  SegmentedControl,
  Textarea,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { ITEMS_PER_PAGE } from '@/lib/optionLetters';
import { TYPE_VARIANT } from './ExerciseRow';
import type { AnswerBoxFill, AnswerBoxLines, Uuid } from '@/lib/api/types';
import {
  ANSWER_BOX_FILLS,
  ANSWER_BOX_LINES,
  MAX_SHEET_ITEMS,
  answerBoxOf,
  type AnswerBox,
  type DraftSheet,
} from './useDraftSheet';

interface Props {
  draft: DraftSheet;
  onAdd: () => void;
  /** Rendered under the list: the page budget, and the generate action. */
  footer?: React.ReactNode;
}

/**
 * What is actually going on the paper, in the order it will print.
 *
 * Reordering offers two affordances on purpose. The arrows are the accessible
 * path — keyboard-reachable, 44 px, and the only one that works on a phone
 * with assistive touch — and the drag handle is the fast one for a mouse. The
 * handle is HTML5 drag-and-drop rather than a library: the Worker bundle has a
 * 3 MiB ceiling (decisions-log D25) and a sortable list is not worth 40 kB of it.
 */
export function SheetComposer({ draft, onAdd, footer }: Props) {
  const t = useTranslations('builder');
  const ts = useTranslations('sheets');
  const tc = useTranslations('common');
  const tx = useTranslations('exercise');
  const ta = useTranslations('adaptive');

  const [editing, setEditing] = useState<string | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-h3">{t('onSheet')}</h2>
        <Badge variant={draft.count > 0 ? 'primary' : 'neutral'}>
          {t('exerciseCount', { count: draft.count })}
        </Badge>
      </div>

      {draft.count === 0 ? (
        <EmptyState
          illustration={<IconSheet size={48} aria-hidden />}
          title={t('emptySheetTitle')}
          description={t('emptySheetBody')}
          size="sm"
        />
      ) : (
        <>
          <p className="text-body-s text-ink-500">{t('reorderHelp')}</p>
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
                    {/* Statement across the full width, actions on their own
                        row beneath it. Competing for horizontal space with four
                        buttons left roughly fifteen characters a line once the
                        preview was open and this column narrowed — and the
                        statement is body-l because it is what gets printed, so
                        it cannot shrink to fit. */}
                    <div className="flex items-start gap-2">
                      <span
                        className="mt-1.5 shrink-0 cursor-grab text-ink-300"
                        aria-hidden
                        title={t('reorderHelp')}
                      >
                        <IconDrag size={18} />
                      </span>
                      <span
                        className="mono mt-1 w-5 shrink-0 text-body-s text-ink-500"
                        data-numeric
                      >
                        {index + 1}
                      </span>
                      <div className="mt-0.5 flex min-w-0 flex-grow flex-wrap items-center gap-2">
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

                    {exercise.type === 'open' ? (
                      <AnswerBoxControl
                        exerciseId={exercise.id}
                        box={answerBoxOf(item)}
                        onChange={draft.setAnswerBox}
                      />
                    ) : null}

                    <div className="mt-1 flex justify-end">
                      <IconButton
                        label={ts('editStatement')}
                        icon={<IconEdit />}
                        variant="ghost"
                        size="sm"
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
                  </Panel>
                </li>
              );
            })}
          </ol>
        </>
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

      <SheetBudget draft={draft} />
      {footer}
    </Card>
  );
}

/**
 * The written-answer box under an open item: its height, and what is printed
 * inside it. Two segmented controls rather than a free number — the paper
 * reserves room for exactly these heights, and a box the pagination did not
 * plan for is a box the scanner cannot find.
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
  return (
    <Panel sunken className="mt-2 ml-7 flex flex-col gap-2" data-answer-box-control>
      <span className="text-label uppercase text-ink-700">
        {t('boxTitle')}
      </span>
      <SegmentedControl<`${AnswerBoxLines}`>
        label={t('boxLines')}
        block
        value={`${box.lines}`}
        onValueChange={(value) => onChange(exerciseId, { lines: Number(value) as AnswerBoxLines })}
        options={ANSWER_BOX_LINES.map((lines) => ({
          value: `${lines}` as `${AnswerBoxLines}`,
          label: t('boxLinesOption', { count: lines }),
        }))}
      />
      <SegmentedControl<AnswerBoxFill>
        label={t('boxFill')}
        block
        value={box.fill}
        onValueChange={(fill) => onChange(exerciseId, { fill })}
        options={ANSWER_BOX_FILLS.map((fill) => ({ value: fill, label: fillLabel[fill] }))}
      />
      <p className="text-body-s text-ink-500">{t('boxHelp')}</p>
    </Panel>
  );
}

/**
 * How much paper this is, without opening the preview.
 *
 * The preview is closed by default, so this is the only thing standing between
 * a teacher and forty exercises on a grid that holds sixteen a page. It reports
 * the floor the answer grid forces; the server preview is the authority on the
 * real page count, because statement height also decides it.
 */
function SheetBudget({ draft }: { draft: DraftSheet }) {
  const t = useTranslations('builder');
  if (draft.count === 0) return null;

  const overflows = draft.count > ITEMS_PER_PAGE;
  return (
    <Panel sunken className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <IconSheet size={20} className="text-ink-500" aria-hidden />
          <span className="font-display font-semibold">
            {t('pagesA4', { count: draft.minPages })}
          </span>
        </span>
        <span
          className={`mono text-body-s ${draft.isFull ? 'text-warn-600' : 'text-ink-500'}`}
          data-numeric
        >
          {t('itemsOfMax', { count: draft.count, max: MAX_SHEET_ITEMS })}
        </span>
      </div>
      {overflows ? (
        <p
          className="flex items-start gap-2 rounded-sm bg-warn-100 p-2 text-body-s text-warn-600"
          role="status"
        >
          <IconWarning size={18} className="mt-0.5 shrink-0" aria-hidden />
          {t('pagesA4', { count: draft.minPages })}
        </p>
      ) : null}
    </Panel>
  );
}

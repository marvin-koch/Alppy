'use client';

import {
  Button,
  Field,
  IconClose,
  IconMcq,
  IconButton,
  IconPlus,
  IconTruefalse,
  Input,
  Modal,
  Panel,
  Radio,
  SegmentedControl,
  Select,
  Textarea,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useCreateExercise } from '@/lib/api/queries';
import { apiErrorMessage } from '@/lib/api/error-message';
import { MAX_OPTIONS, optionLetters } from '@/lib/optionLetters';
import type { ApiLocale, ExerciseOut, ExerciseType, Uuid } from '@/lib/api/types';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  subjectId: Uuid;
  language: ApiLocale;
  /**
   * The Theme this sheet is filed under, or null when the teacher has not
   * chosen one (or chose the `unfiled` pseudo-node, which is not a filing).
   *
   * It travels with the exercise so the API can credit that Theme's primary
   * competency: an exercise tagged with nothing produces no mastery evidence
   * at all, because `load_attempt_inputs` inner-joins `exercise_competency`.
   */
  chapterId?: Uuid | null;
  onCreated: (exercise: ExerciseOut) => void;
}

/**
 * The plus button: an exercise the teacher writes themselves.
 *
 * Two steps, because the type decides the form and half the fields are
 * meaningless for the other two types. It lands in the corpus as
 * `origin: 'teacher'` — reusable next term, and honestly neither a textbook
 * transcription nor a model's proposal.
 */
export function AddExerciseModal({
  open,
  onOpenChange,
  subjectId,
  language,
  chapterId = null,
  onCreated,
}: Props) {
  const t = useTranslations('newExercise');
  const tc = useTranslations('common');
  const tx = useTranslations('exercise');
  const te = useTranslations('errors.code');

  const [type, setType] = useState<ExerciseType | null>(null);
  const [statement, setStatement] = useState('');
  const [options, setOptions] = useState<string[]>(['', '']);
  // Nullable on purpose. Deleting the option currently marked correct leaves
  // the key genuinely undefined, and the old code shifted the index down
  // instead — silently marking whichever option slid into that slot as the
  // right answer. That key is what the answer sheet prints and what the scan
  // pipeline grades against, so a wrong one is a class marked against a
  // sentence nobody chose.
  const [answerIndex, setAnswerIndex] = useState<number | null>(0);
  const [answerBool, setAnswerBool] = useState<'true' | 'false'>('true');
  const [answerText, setAnswerText] = useState('');
  const [difficulty, setDifficulty] = useState(3);
  const [itemLanguage, setItemLanguage] = useState<ApiLocale>(language);
  const [touched, setTouched] = useState(false);

  const create = useCreateExercise();
  const letters = optionLetters(type ?? 'mcq', itemLanguage);

  function reset() {
    setType(null);
    setStatement('');
    setOptions(['', '']);
    setAnswerIndex(0);
    setAnswerBool('true');
    setAnswerText('');
    setDifficulty(3);
    setItemLanguage(language);
    setTouched(false);
    create.reset();
  }

  function close() {
    reset();
    onOpenChange(false);
  }

  const filled = options.map((o) => o.trim()).filter(Boolean);
  const statementError = touched && !statement.trim() ? t('statementRequired') : undefined;
  const optionsError =
    touched && type === 'mcq' && filled.length < 2 ? t('twoAnswersRequired') : undefined;
  const answerError =
    touched && type === 'mcq' && (answerIndex === null || !options[answerIndex]?.trim())
      ? t('correctRequired')
      : undefined;

  function submit() {
    setTouched(true);
    if (!type || !statement.trim()) return;
    if (type === 'mcq' && (filled.length < 2 || answerIndex === null || !options[answerIndex]?.trim()))
      return;

    create.mutate(
      {
        subject_id: subjectId,
        type,
        language: itemLanguage,
        ...(chapterId ? { chapter_id: chapterId } : {}),
        statement: statement.trim(),
        difficulty,
        ...(type === 'mcq'
          ? {
              options: options.map((o) => o.trim()).filter(Boolean),
              // The key follows the option, not its index: dropping a blank
              // field above the correct answer would otherwise re-point it.
              answer_index: options
                .map((o, i) => ({ o: o.trim(), i }))
                .filter((entry) => entry.o)
                .findIndex((entry) => entry.i === answerIndex),
            }
          : {}),
        ...(type === 'true_false' ? { answer_bool: answerBool === 'true' } : {}),
        ...(type === 'open' && answerText.trim() ? { answer_text: answerText.trim() } : {}),
      },
      {
        onSuccess: (exercise) => {
          onCreated(exercise);
          close();
        },
      },
    );
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={type ? t('newOf', { type: tx(`type.${type}`) }) : t('title')}
      description={type ? t('addedToCorpus') : t('subtitle')}
      closeLabel={t('close')}
      size="lg"
      footer={
        type ? (
          <>
            <Button variant="secondary" onClick={() => setType(null)}>
              {t('back')}
            </Button>
            <Button
              variant="primary"
              onClick={submit}
              loading={create.isPending}
              busyLabel={tc('loading')}
            >
              {t('submit')}
            </Button>
          </>
        ) : (
          <Button variant="secondary" onClick={close}>
            {t('cancel')}
          </Button>
        )
      }
    >
      {type === null ? (
        <div className="flex flex-col gap-3">
          <TypeChoice
            icon={<IconMcq size={24} />}
            tint="bg-info-100 text-info-600"
            title={tx('type.mcq')}
            description={t('mcqHelp', { max: MAX_OPTIONS })}
            onClick={() => setType('mcq')}
          />
          <TypeChoice
            icon={<IconTruefalse size={24} />}
            tint="bg-success-100 text-success-600"
            title={tx('type.true_false')}
            description={t('trueFalseHelp')}
            onClick={() => setType('true_false')}
          />
          <TypeChoice
            icon={<IconPlus size={24} />}
            tint="bg-warn-100 text-warn-600"
            title={tx('type.open')}
            description={t('openHelp')}
            onClick={() => setType('open')}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Field label={t('statement')} help={t('statementHelp')} error={statementError} required>
            <Textarea
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              rows={3}
              className="text-body-l"
            />
          </Field>

          {type === 'mcq' ? (
            <Field
              as="fieldset"
              label={t('answers')}
              help={t('answersCap', { count: filled.length, max: MAX_OPTIONS })}
              error={optionsError ?? answerError}
            >
              <div className="flex flex-col gap-2">
                {options.map((option, index) => (
                  <div key={index} className="flex items-center gap-2">
                    {/* The radio's visible label is the letter the sheet
                        prints beside that bubble, so choosing the key and
                        reading the paper use the same glyph. */}
                    <Radio
                      name="correct-answer"
                      value={String(index)}
                      checked={answerIndex === index}
                      onChange={() => setAnswerIndex(index)}
                      label={<span className="mono">{letters[index] ?? index + 1}</span>}
                      aria-label={t('markCorrect', {
                        letter: letters[index] ?? String(index + 1),
                      })}
                    />
                    <Input
                      value={option}
                      aria-label={`${t('answers')} ${letters[index] ?? index + 1}`}
                      onChange={(e) => {
                        const next = e.target.value;
                        setOptions((current) =>
                          current.map((o, i) => (i === index ? next : o)),
                        );
                      }}
                    />
                    <IconButton
                      label={t('removeAnswer', { letter: letters[index] ?? String(index + 1) })}
                      icon={<IconClose />}
                      variant="ghost"
                      size="sm"
                      disabled={options.length <= 2}
                      onClick={() => {
                        setOptions((current) => current.filter((_, i) => i !== index));
                        setAnswerIndex((current) => {
                          if (current === null) return null;
                          // The correct answer was the one just deleted: it is
                          // now unset, and validation says so, rather than
                          // quietly pointing at its neighbour.
                          if (current === index) return null;
                          return current > index ? current - 1 : current;
                        });
                      }}
                    />
                  </div>
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  leadingIcon={<IconPlus />}
                  // Capped at what the printed grid draws: a fifth option would
                  // key the answer to a bubble that is not on the paper.
                  disabled={options.length >= MAX_OPTIONS}
                  onClick={() => setOptions((current) => [...current, ''])}
                  className="self-start"
                >
                  {t('addAnswer')}
                </Button>
              </div>
            </Field>
          ) : null}

          {type === 'true_false' ? (
            <Field as="fieldset" label={t('correctAnswer')} help={t('tfHelp')}>
              <SegmentedControl
                label={t('correctAnswer')}
                value={answerBool}
                onValueChange={(value) => setAnswerBool(value as 'true' | 'false')}
                options={[
                  { value: 'true', label: tx('true') },
                  { value: 'false', label: tx('false') },
                ]}
                block
              />
            </Field>
          ) : null}

          {type === 'open' ? (
            <>
              <Field label={t('expectedAnswer')}>
                <Input value={answerText} onChange={(e) => setAnswerText(e.target.value)} />
              </Field>
              <Panel className="border-warn-500 bg-warn-100">
                <p className="text-body-s text-warn-600">{t('openWarning')}</p>
              </Panel>
            </>
          ) : null}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field as="fieldset" label={t('difficulty')}>
              <SegmentedControl
                label={t('difficulty')}
                value={String(difficulty)}
                onValueChange={(value) => setDifficulty(Number(value))}
                options={[1, 2, 3, 4, 5].map((level) => ({
                  value: String(level),
                  label: String(level),
                }))}
                block
              />
            </Field>
            <Field label={t('language')}>
              <Select
                value={itemLanguage}
                onChange={(e) => setItemLanguage(e.currentTarget.value as ApiLocale)}
              >
                <option value="fr">Français</option>
                <option value="de">Deutsch</option>
                <option value="en">English</option>
              </Select>
            </Field>
          </div>

          {create.isError ? (
            <p className="text-body-s text-danger-600" role="alert">
              {apiErrorMessage(create.error, te)}
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

function TypeChoice({
  icon,
  tint,
  title,
  description,
  onClick,
}: {
  icon: React.ReactNode;
  tint: string;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-11 cursor-pointer items-center gap-3.5 rounded-md border-2 border-line bg-surface p-4 text-left transition-colors hover:border-primary-500 hover:bg-primary-050"
    >
      <span
        className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md ${tint}`}
        aria-hidden
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block font-display font-semibold">{title}</span>
        <span className="block text-body-s text-ink-700">{description}</span>
      </span>
    </button>
  );
}

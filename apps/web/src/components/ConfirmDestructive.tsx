'use client';

import { Button, Field, Input, Modal } from '@alppy/ui';
import { useState } from 'react';

export interface ConfirmDestructiveProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What the dialog IS — never the control that opened it. */
  title: string;
  /** What will be destroyed, in the teacher's terms. Not "are you sure?". */
  description: React.ReactNode;
  /**
   * The exact string the caller must type back. When given, the confirm
   * button stays disabled until it matches.
   *
   * A boolean "yes I'm sure" is the same click wherever the pointer happens
   * to be; typing an identifier is the only gesture that proves the teacher
   * meant THIS row. It is the pupil's uid, which is already in front of them
   * on the paper.
   */
  confirmWith?: string;
  confirmWithLabel?: string;
  /** An escape hatch that is usually what they actually wanted. */
  alternative?: React.ReactNode;
  cancelLabel: string;
  confirmLabel: string;
  closeLabel: string;
  pending?: boolean;
  error?: React.ReactNode;
  onConfirm: () => void;
}

/**
 * The one dialog that destroys something.
 *
 * Deliberately not a generic `<Confirm>`: everything about it — the danger
 * button, the typed identifier, the alternative offered beside it — exists
 * because the action cannot be undone. A dialog that also served "discard
 * draft?" would lose all of that to its own flexibility.
 */
export function ConfirmDestructive({
  open,
  onOpenChange,
  title,
  description,
  confirmWith,
  confirmWithLabel,
  alternative,
  cancelLabel,
  confirmLabel,
  closeLabel,
  pending = false,
  error,
  onConfirm,
}: ConfirmDestructiveProps) {
  const [typed, setTyped] = useState('');
  const armed = confirmWith === undefined || typed.trim() === confirmWith;

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        // Reopening must never inherit a half-typed confirmation from the
        // last row the teacher looked at.
        if (!next) setTyped('');
        onOpenChange(next);
      }}
      title={title}
      closeLabel={closeLabel}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button variant="danger" disabled={!armed || pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="rounded-md border border-danger-500 bg-danger-100 p-4 text-body-s text-ink-700">
          {description}
        </div>
        {alternative}
        {confirmWith !== undefined ? (
          <Field label={confirmWithLabel ?? confirmWith} error={error}>
            <Input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        ) : null}
      </div>
    </Modal>
  );
}

/**
 * A value the teacher may read but not change.
 *
 * Not a `<Input disabled>`: a disabled input renders its text in the same
 * muted grey as a placeholder, so `7B_01` read as an EMPTY field with a hint
 * in it rather than as the pupil's actual identifier. The teacher could not
 * tell whether there was a value at all — which is the opposite of the point,
 * since these fields are shown precisely so the rule is visible.
 *
 * So: a real value, in ink, in a box whose weaker border says it is settled.
 */
export function LockedValue({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex min-h-11 items-center rounded-md border border-line bg-surface-2 px-3.5 py-2 text-body text-ink-700">
      {children}
    </p>
  );
}

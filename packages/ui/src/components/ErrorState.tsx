import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { IconWarning } from '../icons/set';

export interface ErrorStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /**
   * The failing request's id, for a teacher to read out when they report this.
   *
   * `ApiError.requestId` was parsed off every failed response and displayed
   * nowhere except the `global-error` boundary, which is the least likely of all
   * of them to fire (G18). A support conversation that starts with an id is a
   * different conversation from one that starts with "it said it did not work".
   *
   * Rendered small, monospace and last: it is the only string on this component
   * that is not addressed to the teacher, so it must not compete with the sentence
   * that is.
   */
  requestId?: string | null;
  /**
   * Technical detail the teacher can quote in a support message. Rendered as
   * data (`[data-transcription]` → mono) because that is what it is.
   */
  details?: string;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  /** Announce on mount. Turn off when several errors render at once. */
  announce?: boolean;
}

/** Every screen ships one. Colour is never the message: the icon and the text are. */
export const ErrorState = forwardRef<HTMLDivElement, ErrorStateProps>(function ErrorState(
  {
    title,
    description,
    details,
    requestId,
    action,
    secondaryAction,
    announce = true,
    className,
    children,
    ...rest
  },
  ref,
) {
  return (
    <div
      ref={ref}
      role={announce ? 'alert' : undefined}
      className={cx('flex flex-col items-center gap-3 px-4 py-10 text-center sm:py-14', className)}
      {...rest}
    >
      <span
        aria-hidden="true"
        className="inline-flex h-14 w-14 items-center justify-center rounded-pill bg-danger-100 text-danger-600"
      >
        <IconWarning size={28} />
      </span>
      <h3 className="font-display text-h2 font-bold text-ink-900">{title}</h3>
      {description ? <p className="max-w-prose text-body text-ink-700">{description}</p> : null}
      {details ? (
        <pre
          data-transcription=""
          className="ard-panel max-w-full overflow-x-auto text-left text-body-s whitespace-pre-wrap"
        >
          {details}
        </pre>
      ) : null}
      {requestId ? (
        <p className="mono text-body-s text-ink-500" data-request-id={requestId}>
          {requestId}
        </p>
      ) : null}
      {children}
      {action || secondaryAction ? (
        <div className="mt-2 flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:justify-center">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
});

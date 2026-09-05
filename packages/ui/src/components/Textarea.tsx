import { forwardRef, type TextareaHTMLAttributes } from 'react';
import { cx } from '../lib/cx';
import { useFieldControl } from './Field';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
  /** Transcribed / extracted text is data: renders in mono so it reads as data. */
  transcription?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { invalid, transcription = false, className, id, required, rows = 4, ...rest },
  ref,
) {
  const aria = useFieldControl({ id, describedBy: rest['aria-describedby'], invalid, required });
  return (
    <textarea
      ref={ref}
      rows={rows}
      {...rest}
      {...aria}
      {...(transcription ? { 'data-transcription': '' } : {})}
      className={cx('ard-input', className)}
    />
  );
});

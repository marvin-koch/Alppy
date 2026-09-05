import { forwardRef, useId, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { cx } from '../lib/cx';
import { mergeRefs } from '../lib/refs';
import { IconCamera, IconUpload } from '../icons/set';
import { useFieldContext } from './Field';

export interface FileDropProps {
  onFiles: (files: File[]) => void;
  /** Comma-separated accept list, e.g. `'application/pdf'` or `'image/*'`. */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  /** The instruction inside the zone. Supplied by the app. */
  label: ReactNode;
  /** Secondary line: formats, size limit, page count. */
  description?: ReactNode;
  /**
   * Adds a second control that opens the phone's rear camera directly
   * (`capture="environment"`) — the scan-upload path in F2. Hidden from `md`
   * up, where there is no camera worth opening.
   */
  camera?: boolean;
  /** Accessible name of the camera control. Required when `camera` is on. */
  cameraLabel?: string;
  /** Contents below the zone: the files already chosen. */
  children?: ReactNode;
  className?: string;
  invalid?: boolean;
  id?: string;
}

/**
 * Drag-and-drop, click, and — on a phone — the camera. The drop zone is a real
 * `<input type="file">` inside a `<label>`, so keyboard and screen readers get
 * the native control and drag-and-drop is pure enhancement.
 */
export const FileDrop = forwardRef<HTMLInputElement, FileDropProps>(function FileDrop(
  {
    onFiles,
    accept,
    multiple = false,
    disabled = false,
    label,
    description,
    camera = false,
    cameraLabel,
    children,
    className,
    invalid,
    id,
  },
  ref,
) {
  const generated = useId();
  const field = useFieldContext();
  const inputId = id ?? field?.controlId ?? `${generated}-file`;
  const cameraId = `${generated}-camera`;
  const [dragging, setDragging] = useState(false);
  const inner = useRef<HTMLInputElement | null>(null);
  const isInvalid = invalid ?? field?.invalid ?? false;

  const emit = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    onFiles(Array.from(list));
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    emit(event.dataTransfer.files);
  };

  return (
    <div className={cx('flex flex-col gap-3', className)}>
      <label
        htmlFor={inputId}
        data-dragging={dragging ? 'true' : undefined}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          'flex min-h-[9rem] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg',
          'border-2 border-dashed p-6 text-center transition-colors',
          dragging ? 'border-primary-500 bg-primary-050' : 'border-line-strong bg-surface-2',
          isInvalid && 'border-danger-500',
          disabled && 'cursor-not-allowed opacity-60',
          'focus-within:shadow-[var(--focus-ring)]',
        )}
      >
        <IconUpload size={28} className="text-primary-500" />
        <span className="font-display text-body font-semibold text-ink-900">{label}</span>
        {description ? <span className="text-body-s text-ink-500">{description}</span> : null}
        <input
          ref={mergeRefs(ref, inner)}
          id={inputId}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          aria-invalid={isInvalid ? true : undefined}
          aria-describedby={field?.describedBy}
          onChange={(event) => {
            emit(event.currentTarget.files);
            event.currentTarget.value = '';
          }}
          className="visually-hidden"
        />
      </label>

      {camera ? (
        <div className="md:hidden">
          <label
            htmlFor={cameraId}
            className="ard-btn w-full cursor-pointer"
            data-variant="secondary"
            data-block="true"
          >
            <IconCamera size={20} />
            {cameraLabel}
            <input
              id={cameraId}
              type="file"
              accept={accept ?? 'image/*'}
              capture="environment"
              multiple={multiple}
              disabled={disabled}
              onChange={(event) => {
                emit(event.currentTarget.files);
                event.currentTarget.value = '';
              }}
              className="visually-hidden"
            />
          </label>
        </div>
      ) : null}

      {children}
    </div>
  );
});

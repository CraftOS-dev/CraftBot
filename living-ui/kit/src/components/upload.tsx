/**
 * File upload presets — PocketBase stores files ON a record's file field, so
 * these upload into a given collection + field and hand back the public URL.
 *
 *   // Attach a file, creating (or updating) a record in `uploads`:
 *   <FileUpload collection="uploads" field="file"
 *     onUploaded={(f) => attach(f.url)} />
 *
 *   // An image field on a form (upload + preview), stores the file URL:
 *   <ImageInput collection="uploads" field="file" value={coverUrl} onValue={setCoverUrl} />
 *
 * The `field` must be a `file` field on the collection. Pass `recordId` to
 * update an existing record instead of creating a new one.
 */
import { useRef, useState } from 'react';
import { getPbClient } from '../pb/client.ts';
import { Spinner } from './Spinner.tsx';
import { UploadIcon, XIcon } from './icons.tsx';

export interface UploadedFile {
  recordId: string;
  filename: string;
  url: string;
}

async function uploadToRecord(
  collection: string,
  field: string,
  file: File,
  recordId?: string,
): Promise<UploadedFile> {
  const client = getPbClient();
  const form = new FormData();
  form.append(field, file);
  const record =
    recordId !== undefined
      ? await client.call((pb) => pb.collection(collection).update(recordId, form))
      : await client.call((pb) => pb.collection(collection).create(form));
  const filename = String((record as Record<string, unknown>)[field] ?? '');
  const url = client.pb.files.getURL(record, filename);
  return { recordId: record.id, filename, url };
}

export interface FileUploadProps {
  /** Collection that owns the file field. */
  collection: string;
  /** Name of the `file` field on the collection. */
  field: string;
  /** Update this record instead of creating a new one. */
  recordId?: string | undefined;
  /** Called with the stored file's metadata after a successful upload. */
  onUploaded: (file: UploadedFile) => void;
  /** Accept filter, e.g. "image/*" or ".csv" (native input semantics). */
  accept?: string | undefined;
  label?: string | undefined;
}

export function FileUpload({
  collection,
  field,
  recordId,
  onUploaded,
  accept,
  label,
}: FileUploadProps): React.JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const handle = async (file: File | undefined | null): Promise<void> => {
    if (file === undefined || file === null) return;
    setBusy(true);
    setError(null);
    try {
      onUploaded(await uploadToRecord(collection, field, file, recordId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (inputRef.current !== null) inputRef.current.value = '';
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {label !== undefined && <span className="text-sm font-medium">{label}</span>}
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void handle(e.dataTransfer.files.item(0));
        }}
        className={
          'flex cursor-pointer items-center justify-center gap-2 rounded-[var(--lui-radius)] border border-dashed px-4 py-6 text-sm text-[var(--lui-muted)] transition-colors ' +
          (dragOver
            ? 'border-[var(--lui-accent)] bg-[var(--lui-accent)]/5'
            : 'border-[var(--lui-border)] bg-[var(--lui-surface)]')
        }
      >
        {busy ? <Spinner size={14} /> : <UploadIcon size={14} />}
        {busy ? 'Uploading…' : 'Drop a file or click to browse'}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => void handle(e.target.files?.item(0))}
      />
      {error !== null && <span className="text-xs text-red-500">{error}</span>}
    </div>
  );
}

export interface ImageInputProps {
  collection: string;
  field: string;
  recordId?: string | undefined;
  /** Stored file URL (the `url` from upload) or null. */
  value: string | null;
  onValue: (url: string | null) => void;
  label?: string | undefined;
  /** Preview height in px (default 120). */
  height?: number | undefined;
}

export function ImageInput({
  collection,
  field,
  recordId,
  value,
  onValue,
  label,
  height = 120,
}: ImageInputProps): React.JSX.Element {
  if (value !== null && value !== '') {
    return (
      <div className="flex flex-col gap-1.5">
        {label !== undefined && <span className="text-sm font-medium">{label}</span>}
        <div className="relative inline-block">
          <img
            src={value}
            alt={label ?? 'Uploaded image'}
            style={{ maxHeight: height }}
            className="block max-w-full rounded-[var(--lui-radius)] border border-[var(--lui-border)]"
          />
          <button
            type="button"
            onClick={() => onValue(null)}
            aria-label="Remove image"
            className="absolute right-1 top-1 inline-flex rounded-full bg-black/60 p-1 text-white"
          >
            <XIcon size={12} />
          </button>
        </div>
      </div>
    );
  }
  return (
    <FileUpload
      collection={collection}
      field={field}
      recordId={recordId}
      label={label}
      accept="image/*"
      onUploaded={(f) => onValue(f.url)}
    />
  );
}

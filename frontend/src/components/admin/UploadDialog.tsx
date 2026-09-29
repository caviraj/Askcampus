/**
 * DESIGN_SYSTEM.md section 8's upload dialog.
 *
 * Three of its requirements shape this file:
 *
 * - "Progress is a determinate bar with the current step named." The bar is
 *   never a spinner, and the step's own name sits beside it. The first step is
 *   real byte progress; steps two and three are server states the dialog polls
 *   for, so the bar advances when a step *completes*, not on a timer.
 * - "Validation messages appear under the field." The message is rendered in
 *   the field's own wrapper and wired to it with `aria-describedby`, so a
 *   screen reader reads the reason with the input rather than after the form.
 * - The file field is "drag and drop plus button".
 *
 * `role="dialog"` rather than a native `<dialog>`: jsdom does not implement
 * `showModal`, so a native element would be untestable without a polyfill in
 * the test setup, and the focus and Escape handling it would give are a dozen
 * lines here.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ALLOWED_UPLOAD_EXTENSIONS,
  ADMIN_COPY,
  DOCUMENT_CATEGORIES,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_MB,
  UPLOAD_STEPS,
} from "../../lib/constants";
import { fetchDocument, uploadDocumentWithProgress } from "../../lib/api";
import { formatBytes, formatCategory } from "../../lib/format";
import { toErrorView } from "../../lib/errors";
import { usePolling } from "../../hooks/useAsync";
import { UploadIcon } from "../Icons";
import type { AdminDocument, ErrorView } from "../../lib/types";

interface UploadDialogProps {
  token: string;
  onClose: () => void;
  /** Called once a document reaches `ready`, so the list behind can refresh. */
  onUploaded: (document: AdminDocument) => void;
}

type Phase =
  | { kind: "form" }
  | { kind: "uploading"; fraction: number }
  | { kind: "processing"; document: AdminDocument }
  | { kind: "ready"; document: AdminDocument }
  | { kind: "failed"; error: ErrorView };

/** How often the dialog asks whether processing has moved on. Two seconds is
 *  frequent enough that a document finishing feels immediate and slow enough
 *  that a run of a few minutes does not become a flood of requests. */
const POLL_INTERVAL_MS = 2000;

export function UploadDialog({ token, onClose, onUploaded }: UploadDialogProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "form" });
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [academicYear, setAcademicYear] = useState("");
  const [department, setDepartment] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);

  const fileInput = useRef<HTMLInputElement>(null);

  // Focus moves into the dialog when it opens, so the keyboard does not stay
  // on the button that opened it, behind the overlay.
  useEffect(() => {
    fileInput.current?.focus();
  }, []);

  // Escape closes, but only from the form. Once bytes are going up, closing
  // would abandon a request the admin cannot see or cancel.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && phase.kind === "form") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [phase.kind, onClose]);

  const processing = phase.kind === "processing";
  usePolling(
    useCallback(() => {
      if (phase.kind !== "processing") return;
      void fetchDocument(token, phase.document.id)
        .then((document) => {
          if (document.status === "ready") {
            setPhase({ kind: "ready", document });
            onUploaded(document);
          } else if (document.status === "failed") {
            setPhase({
              kind: "failed",
              error: {
                text: document.error_message ?? ADMIN_COPY.uploadFailed,
                cooldownSeconds: null,
                canRetry: true,
              },
            });
          } else {
            setPhase({ kind: "processing", document });
          }
        })
        .catch(() => {
          // A single failed poll is not a failed upload -- the document is
          // still processing on the server. The next tick asks again.
        });
    }, [token, phase, onUploaded]),
    { active: processing, intervalMs: POLL_INTERVAL_MS },
  );

  const pickFile = (chosen: File | null) => {
    setFile(chosen);
    setErrors((current) => ({ ...current, file: "" }));
    // The title is a required field an admin would otherwise retype from the
    // filename. Only filled when empty, so a typed title is never overwritten.
    if (chosen && title.trim() === "") {
      setTitle(chosen.name.replace(/\.[^.]+$/, ""));
    }
  };

  const validate = (): boolean => {
    const found: Record<string, string> = {};
    if (!file) found.file = "Choose a file to upload.";
    else if (file.size > MAX_UPLOAD_BYTES) {
      found.file = `That file is ${formatBytes(file.size)}. The limit is ${MAX_UPLOAD_MB} MB.`;
    } else if (!hasAllowedExtension(file.name)) {
      found.file = `That file type is not supported. Use ${ALLOWED_UPLOAD_EXTENSIONS.join(", ")}.`;
    }
    if (title.trim() === "") found.title = "Enter a title.";
    if (category === "") found.category = "Choose a category.";
    setErrors(found);
    return Object.keys(found).length === 0;
  };

  const submit = async () => {
    // `validate` first, and unconditionally. Checking `!file` here instead
    // would short-circuit before the validator ran, so pressing Upload with
    // nothing chosen would do nothing and say nothing -- the one outcome
    // section 9's voice rules out.
    if (!validate()) return;
    if (file === null) return; // Unreachable: the validator reports a missing file.
    setPhase({ kind: "uploading", fraction: 0 });
    try {
      const document = await uploadDocumentWithProgress(
        token,
        file,
        {
          title: title.trim(),
          category,
          ...(academicYear.trim() ? { academic_year: academicYear.trim() } : {}),
          ...(department.trim() ? { department: department.trim() } : {}),
        },
        (fraction) => setPhase({ kind: "uploading", fraction }),
      );
      // The POST returns as soon as the row exists and the background task is
      // queued, so the document is `uploaded`, not `ready`. Everything after
      // this point is the server telling us how far it has got.
      setPhase(
        document.status === "ready"
          ? { kind: "ready", document }
          : { kind: "processing", document },
      );
      if (document.status === "ready") onUploaded(document);
    } catch (cause) {
      setPhase({ kind: "failed", error: toErrorView(cause) });
    }
  };

  const stepIndex = stepOf(phase);
  const progress = progressOf(phase, stepIndex);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-dialog-title"
        className="w-full max-w-lg rounded-panel border border-rule bg-surface p-5"
      >
        <h2 id="upload-dialog-title" className="font-serif text-section-title text-ink">
          Upload a document
        </h2>

        {phase.kind === "form" && (
          <form
            className="mt-4 flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <FileField
              inputRef={fileInput}
              file={file}
              dragging={dragging}
              error={errors.file}
              onPick={pickFile}
              onDragging={setDragging}
            />
            <TextField
              id="upload-title"
              label="Title"
              value={title}
              error={errors.title}
              onChange={setTitle}
            />
            <div className="flex flex-col gap-1">
              <label htmlFor="upload-category" className="font-sans text-ui-label text-ink">
                Category
              </label>
              <select
                id="upload-category"
                value={category}
                aria-invalid={errors.category ? true : undefined}
                aria-describedby={errors.category ? "upload-category-error" : undefined}
                onChange={(event) => {
                  setCategory(event.target.value);
                  setErrors((current) => ({ ...current, category: "" }));
                }}
                className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-ui text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
              >
                <option value="">Choose a category</option>
                {DOCUMENT_CATEGORIES.map((value) => (
                  <option key={value} value={value}>
                    {formatCategory(value)}
                  </option>
                ))}
              </select>
              <FieldError id="upload-category-error" message={errors.category} />
            </div>
            <TextField
              id="upload-year"
              label="Academic year (optional)"
              value={academicYear}
              onChange={setAcademicYear}
            />
            <TextField
              id="upload-department"
              label="Department (optional)"
              value={department}
              onChange={setDepartment}
            />
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                className="h-11 rounded-control border border-marine px-4 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="h-11 rounded-control bg-marine px-4 font-sans text-ui-label font-semibold text-white hover:bg-marine-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
              >
                Upload
              </button>
            </div>
          </form>
        )}

        {phase.kind !== "form" && (
          <div className="mt-4 flex flex-col gap-4">
            <StepProgress stepIndex={stepIndex} progress={progress} />

            {phase.kind === "ready" && (
              <p className="text-ui text-ink">{ADMIN_COPY.processingDone}</p>
            )}
            {phase.kind === "failed" && (
              <p className="text-ui text-brick">{phase.error.text}</p>
            )}

            <div className="flex justify-end gap-2">
              {phase.kind === "failed" && (
                <button
                  type="button"
                  onClick={() => {
                    setPhase({ kind: "form" });
                  }}
                  className="h-11 rounded-control border border-marine px-4 font-sans text-ui-label text-marine hover:bg-marine-wash focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
                >
                  Try again
                </button>
              )}
              {(phase.kind === "ready" || phase.kind === "failed") && (
                <button
                  type="button"
                  onClick={onClose}
                  className="h-11 rounded-control bg-marine px-4 font-sans text-ui-label font-semibold text-white hover:bg-marine-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
                >
                  Done
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Which of section 8's three steps is running, or 3 when all are done. */
function stepOf(phase: Phase): number {
  switch (phase.kind) {
    case "uploading":
      return 0;
    case "processing":
      // The row exists but extraction has not been claimed yet, then the
      // server moves it to `processing` for chunking and embedding. Those are
      // exactly the spec's second and third steps.
      return phase.document.status === "uploaded" ? 1 : 2;
    case "ready":
      return UPLOAD_STEPS.length;
    default:
      return 0;
  }
}

/**
 * How full the bar is: completed steps as a fraction of three, plus real byte
 * progress inside the first step.
 *
 * Steps two and three report no percentage because the server does not publish
 * one, so the bar advances as each step *completes* and the named step beside
 * it is what says where the work is. Inventing a number that creeps forward on
 * a timer would be a progress bar that lies.
 */
function progressOf(phase: Phase, stepIndex: number): number {
  if (phase.kind === "ready") return 1;
  const withinStep = phase.kind === "uploading" ? phase.fraction : 0;
  return Math.min((stepIndex + withinStep) / UPLOAD_STEPS.length, 1);
}

function StepProgress({ stepIndex, progress }: { stepIndex: number; progress: number }) {
  const done = stepIndex >= UPLOAD_STEPS.length;
  const current = done ? "Ready" : (UPLOAD_STEPS[stepIndex] ?? "");

  return (
    <div className="flex flex-col gap-2">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
        aria-label="Upload progress"
        className="h-2 w-full overflow-hidden rounded-control bg-rule"
      >
        <div
          className="h-full rounded-r-control bg-marine"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
      {/* `aria-live` so the step name is announced as it changes; the bar's
          `aria-valuenow` alone would update silently. */}
      <p aria-live="polite" className="text-ui-label text-ink-soft">
        {current}
      </p>
    </div>
  );
}

function FileField({
  inputRef,
  file,
  dragging,
  error,
  onPick,
  onDragging,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  file: File | null;
  dragging: boolean;
  error: string | undefined;
  onPick: (file: File | null) => void;
  onDragging: (dragging: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-sans text-ui-label text-ink">File</span>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          onDragging(true);
        }}
        onDragLeave={() => onDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          onDragging(false);
          onPick(event.dataTransfer.files[0] ?? null);
        }}
        className={`flex flex-col items-center gap-2 rounded-panel border border-dashed px-4 py-5 text-center ${
          dragging ? "border-marine bg-marine-wash" : "border-rule"
        }`}
      >
        <UploadIcon aria-hidden="true" className="text-ink-soft" />
        <p className="text-ui-label text-ink-soft">
          Drag a PDF, DOCX, or TXT file here, or
        </p>
        {/* The input is visually hidden but real, and the label is the button:
            a styled div that calls `.click()` would not be focusable. */}
        <input
          ref={inputRef}
          id="upload-file"
          type="file"
          accept={ALLOWED_UPLOAD_EXTENSIONS.join(",")}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "upload-file-error" : undefined}
          onChange={(event) => onPick(event.target.files?.[0] ?? null)}
          className="sr-only"
        />
        <label
          htmlFor="upload-file"
          className="inline-flex h-11 cursor-pointer items-center rounded-control border border-marine px-4 font-sans text-ui-label text-marine hover:bg-marine-wash focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-marine"
        >
          Choose a file
        </label>
        {file && <p className="text-meta text-ink-soft">{`${file.name} · ${formatBytes(file.size)}`}</p>}
      </div>
      <FieldError id="upload-file-error" message={error} />
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  error,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  error?: string | undefined;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="font-sans text-ui-label text-ink">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 rounded-control border border-rule bg-surface px-3 font-sans text-ui text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine"
      />
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

/** Under the field, per section 8, and tied to it by `aria-describedby`. The
 *  text is the server's own message where there is one. */
function FieldError({ id, message }: { id: string; message?: string | undefined }) {
  if (!message) return null;
  return (
    <p id={id} className="text-meta text-brick">
      {message}
    </p>
  );
}

function hasAllowedExtension(name: string): boolean {
  const lower = name.toLowerCase();
  return ALLOWED_UPLOAD_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

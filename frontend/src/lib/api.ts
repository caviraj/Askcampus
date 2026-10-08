/**
 * The only module in the app that calls `fetch` (AGENTS.md section 7).
 *
 * Everything it returns is typed, and every failure is an `ApiError` or a
 * `NetworkError` -- callers never see a raw `Response`, so no component has to
 * remember what the error envelope looks like.
 */
import { DEFAULT_API_URL } from "./constants";
import { ApiError, NetworkError } from "./errors";
import type {
  AdminDocument,
  AdminIdentity,
  AdminSession,
  CategoryListResponse,
  ChatRequestPayload,
  ChatResponse,
  DocumentListResponse,
  DocumentStatus,
  FaqListResponse,
  FeedbackRequest,
  QueryListResponse,
  StatsResponse,
  UnansweredGroup,
  UnansweredListResponse,
  UnansweredStatus,
} from "./types";

const baseUrl = (): string => {
  const configured = import.meta.env.VITE_API_URL?.trim();
  // Trailing slashes stripped so `http://host/` and `http://host` cannot
  // produce `//chat`, which some proxies treat as a different path.
  return (configured || DEFAULT_API_URL).replace(/\/+$/, "");
};

/**
 * The Supabase project, for sign-in only.
 *
 * The admin UI authenticates against Supabase Auth and reads nothing else from
 * Supabase: every table has row level security enabled with default-deny, so
 * the anon key returns no rows. All data comes from the FastAPI backend, which
 * holds the service role key (AGENTS.md section 7). These stay in this module
 * for the same reason the chat calls do -- one place that talks to the network.
 */
const supabaseUrl = (): string => (import.meta.env.VITE_SUPABASE_URL ?? "").trim();
const supabaseAnonKey = (): string => (import.meta.env.VITE_SUPABASE_ANON_KEY ?? "").trim();

/** Whether sign-in is even configured, so the login page can say so plainly
 *  rather than failing with a network error the admin cannot act on. */
export const isAuthConfigured = (): boolean => Boolean(supabaseUrl() && supabaseAnonKey());

/** Parse `Retry-After`, which is either delta-seconds or an HTTP date. */
function parseRetryAfter(response: Response): number | null {
  const raw = response.headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const date = Date.parse(raw);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/**
 * Read a response, turning anything that is not a 2xx into a typed error.
 *
 * The body is read once as text and parsed, rather than trusting
 * `response.json()`: a proxy's HTML error page and a truncated body both throw
 * from `json()`, and both need to become the same `NetworkError` rather than an
 * unhandled rejection inside a component.
 */
/**
 * Turn a non-2xx body into the same typed error `readJson` would raise.
 *
 * Split out because the upload takes the XMLHttpRequest path -- `fetch` cannot
 * report upload progress -- and an error from there has to be indistinguishable
 * from one raised anywhere else. Two error mappings that drift would mean a
 * failed upload showing a different message depending on which transport
 * happened to carry it.
 */
function failFromBody(status: number, text: string, retryAfter: number | null): never {
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }

  const envelope = parsed as { detail?: unknown; code?: unknown } | null;
  const detail = typeof envelope?.detail === "string" ? envelope.detail : "";
  const code = typeof envelope?.code === "string" ? envelope.code : "unknown_error";
  if (detail || code !== "unknown_error") {
    throw new ApiError(status, code, detail, retryAfter);
  }
  throw new NetworkError();
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }

  if (!response.ok) failFromBody(response.status, text, parseRetryAfter(response));

  return parsed as T;
}

/** Wrap `fetch` itself: a rejected promise is always a network failure. */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${baseUrl()}${path}`, init);
  } catch (cause) {
    throw new NetworkError(undefined, { cause });
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

export async function askQuestion(payload: ChatRequestPayload): Promise<ChatResponse> {
  const response = await send("/chat", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  return readJson<ChatResponse>(response);
}

export async function sendFeedback(payload: FeedbackRequest): Promise<void> {
  const response = await send("/chat/feedback", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
  // 204 with no body. `readJson` would parse it to null and return, but going
  // through it keeps the error handling in one place.
  await readJson<null>(response);
}

export async function fetchCategories(): Promise<CategoryListResponse> {
  const response = await send("/categories", { method: "GET" });
  return readJson<CategoryListResponse>(response);
}

// ---------------------------------------------------------------------------
// Sign-in. Supabase Auth's password grant, called directly.
// ---------------------------------------------------------------------------

/** Read Supabase's error envelope, which is not the backend's `{detail, code}`
 *  and would otherwise be misread as an unparseable body. */
async function readAuthJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const envelope = parsed as { msg?: unknown; error_description?: unknown; message?: unknown } | null;
    const detail =
      (typeof envelope?.msg === "string" && envelope.msg) ||
      (typeof envelope?.error_description === "string" && envelope.error_description) ||
      (typeof envelope?.message === "string" && envelope.message) ||
      "";
    throw new ApiError(response.status, "invalid_credentials", detail);
  }

  return parsed as T;
}

interface SupabaseTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user?: { email?: string | null } | null;
}

function toSession(token: SupabaseTokenResponse, fallbackEmail: string): AdminSession {
  return {
    accessToken: token.access_token,
    refreshToken: token.refresh_token,
    // Derived from `expires_in` rather than decoded from the JWT: the claim
    // would have to be parsed by hand, and the two say the same thing.
    expiresAt: Date.now() + token.expires_in * 1000,
    email: token.user?.email ?? fallbackEmail,
  };
}

async function authRequest(path: string, body: unknown): Promise<Response> {
  const url = supabaseUrl();
  if (!url || !supabaseAnonKey()) {
    throw new ApiError(503, "Sign-in is not configured.", "auth_not_configured");
  }
  try {
    return await fetch(`${url.replace(/\/+$/, "")}/auth/v1/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: supabaseAnonKey() },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    throw new NetworkError(undefined, { cause });
  }
}

export async function signIn(email: string, password: string): Promise<AdminSession> {
  const response = await authRequest("token?grant_type=password", { email, password });
  return toSession(await readAuthJson<SupabaseTokenResponse>(response), email);
}

export interface SignUpResult {
  session: AdminSession | null;
  needsEmailConfirmation: boolean;
}

export async function signUp(
  email: string,
  password: string,
  metadata?: { role?: string; full_name?: string },
): Promise<SignUpResult> {
  const payload: Record<string, unknown> = { email, password };
  if (metadata) {
    payload.data = metadata;
  }
  const response = await authRequest("signup", payload);
  const data = await readAuthJson<SupabaseTokenResponse & { id?: string }>(response);
  if (data.access_token) {
    return {
      session: toSession(data, email),
      needsEmailConfirmation: false,
    };
  }
  return {
    session: null,
    needsEmailConfirmation: true,
  };
}

export async function refreshSession(refreshToken: string): Promise<AdminSession> {
  const response = await authRequest("token?grant_type=refresh_token", {
    refresh_token: refreshToken,
  });
  return toSession(await readAuthJson<SupabaseTokenResponse>(response), "");
}

// ---------------------------------------------------------------------------
// Admin. Every call carries the access token; the backend reads the role from
// `profiles` on each request, never from the token.
// ---------------------------------------------------------------------------

function bearer(token: string): RequestInit {
  return { method: "GET", headers: { Authorization: `Bearer ${token}` } };
}

function jsonInit(token: string, method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  };
}

/** Build a query string, dropping absent filters rather than sending "null" or
 *  an empty string -- the backend treats a missing filter as no filter. */
function queryString(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

export async function fetchAdminIdentity(token: string): Promise<AdminIdentity> {
  const response = await send("/admin/me", bearer(token));
  return readJson<AdminIdentity>(response);
}

export interface DocumentFilters {
  status?: DocumentStatus | "all";
  category?: string;
  limit?: number;
  offset?: number;
}

export async function fetchDocuments(
  token: string,
  filters: DocumentFilters = {},
): Promise<DocumentListResponse> {
  const path = queryString({
    status: filters.status && filters.status !== "all" ? filters.status : undefined,
    category: filters.category && filters.category !== "all" ? filters.category : undefined,
    limit: filters.limit,
    offset: filters.offset,
  });
  const response = await send(`/admin/documents${path}`, bearer(token));
  return readJson<DocumentListResponse>(response);
}

export async function fetchDocument(token: string, id: string): Promise<AdminDocument> {
  const response = await send(`/admin/documents/${id}`, bearer(token));
  return readJson<AdminDocument>(response);
}

export async function updateDocument(
  token: string,
  id: string,
  patch: Partial<Pick<AdminDocument, "title" | "category" | "academic_year" | "department" | "is_active">>,
): Promise<AdminDocument> {
  const response = await send(`/admin/documents/${id}`, jsonInit(token, "PATCH", patch));
  return readJson<AdminDocument>(response);
}

export interface UploadMetadata {
  title: string;
  category: string;
  academic_year?: string;
  department?: string;
}

function buildUploadForm(file: File, metadata: UploadMetadata): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("title", metadata.title);
  form.append("category", metadata.category);
  if (metadata.academic_year) form.append("academic_year", metadata.academic_year);
  if (metadata.department) form.append("department", metadata.department);
  return form;
}

/** No Content-Type header here or below: the browser sets it together with the
 *  multipart boundary, and setting it by hand omits the boundary, which makes
 *  the body unparseable on the server. */
export async function uploadDocument(
  token: string,
  file: File,
  metadata: UploadMetadata,
): Promise<AdminDocument> {
  const response = await send("/admin/documents", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: buildUploadForm(file, metadata),
  });
  return readJson<AdminDocument>(response);
}

/**
 * The same upload, reporting how much of the file has been sent.
 *
 * XMLHttpRequest rather than `fetch`, and not by preference: `fetch` exposes no
 * upload progress at all -- a streaming request body is not available in stable
 * browsers -- so a determinate bar over the upload (DESIGN_SYSTEM.md section 8)
 * cannot be built on it. This is the one place in the app that does not go
 * through `send`, and it exists only for the progress callback.
 *
 * `onProgress` is called with a fraction of 0..1, and with 1 when the bytes are
 * sent, which is before the server has answered.
 */
export function uploadDocumentWithProgress(
  token: string,
  file: File,
  metadata: UploadMetadata,
  onProgress: (fraction: number) => void,
): Promise<AdminDocument> {
  return new Promise<AdminDocument>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${baseUrl()}/admin/documents`);
    request.setRequestHeader("Authorization", `Bearer ${token}`);

    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(event.loaded / event.total, 1));
      }
    });

    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        try {
          resolve(JSON.parse(request.responseText) as AdminDocument);
        } catch (cause) {
          reject(new NetworkError(undefined, { cause }));
        }
        return;
      }
      try {
        failFromBody(request.status, request.responseText, null);
      } catch (cause) {
        // `failFromBody` always throws an `ApiError` or a `NetworkError`; the
        // guard is for the TypeScript signature, which cannot say so.
        reject(cause instanceof Error ? cause : new NetworkError());
      }
    });

    // A transport failure, an abort and a browser timeout are all the same
    // thing to the admin: the file did not get there.
    request.addEventListener("error", () => reject(new NetworkError()));
    request.addEventListener("abort", () => reject(new NetworkError()));
    request.addEventListener("timeout", () => reject(new NetworkError()));

    onProgress(0);
    request.send(buildUploadForm(file, metadata));
  });
}

export async function reprocessDocument(token: string, id: string): Promise<AdminDocument> {
  const response = await send(`/admin/documents/${id}/reprocess`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return readJson<AdminDocument>(response);
}

export async function replaceDocument(
  token: string,
  id: string,
  file: File,
): Promise<AdminDocument> {
  const form = new FormData();
  form.append("file", file);
  const response = await send(`/admin/documents/${id}/replace`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  return readJson<AdminDocument>(response);
}

export async function deleteDocument(token: string, id: string): Promise<void> {
  const response = await send(`/admin/documents/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  await readJson<null>(response);
}

export async function fetchQueries(
  token: string,
  params: { answered?: boolean; category?: string; limit?: number; offset?: number } = {},
): Promise<QueryListResponse> {
  const path = queryString({
    answered: params.answered,
    category: params.category && params.category !== "all" ? params.category : undefined,
    limit: params.limit,
    offset: params.offset,
  });
  const response = await send(`/admin/queries${path}`, bearer(token));
  return readJson<QueryListResponse>(response);
}

export async function fetchUnanswered(
  token: string,
  params: { status?: UnansweredStatus | "all"; limit?: number; offset?: number } = {},
): Promise<UnansweredListResponse> {
  const path = queryString({
    status: params.status ?? "open",
    limit: params.limit,
    offset: params.offset,
  });
  const response = await send(`/admin/unanswered${path}`, bearer(token));
  return readJson<UnansweredListResponse>(response);
}

export async function resolveUnanswered(
  token: string,
  normalizedHash: string,
  payload: { status: UnansweredStatus; resolved_by_document?: string | null },
): Promise<UnansweredGroup> {
  const response = await send(
    `/admin/unanswered/${encodeURIComponent(normalizedHash)}`,
    jsonInit(token, "PATCH", payload),
  );
  return readJson<UnansweredGroup>(response);
}

export async function fetchFaqs(token: string): Promise<FaqListResponse> {
  const response = await send("/admin/faqs", bearer(token));
  return readJson<FaqListResponse>(response);
}

export async function fetchStats(token: string): Promise<StatsResponse> {
  const response = await send("/admin/stats", bearer(token));
  return readJson<StatsResponse>(response);
}

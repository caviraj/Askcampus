/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** The Supabase project URL. Read by the admin sign-in only; every table has
   *  row level security with default-deny, so the anon key below reaches no
   *  rows (AGENTS.md section 7). */
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

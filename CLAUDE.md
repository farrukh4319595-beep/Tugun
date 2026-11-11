# Tugun — project context for Claude Code

Tugun is a matrix-organization management app for **BARAKA LES** (timber, lumber, profnastil and nail
wholesale/retail, Urganch, Uzbekistan). Departments × staff × cross-department tasks with exactly one
owner ("mas'ul"), attendance via PIN kiosk, company charter (Nizom) and position instructions with
"Tanishdim" acknowledgements, dashboard, AI assignee recommendation.

The user is the company manager, a non-developer. **UI language: Uzbek (Latin).** Talk to the user in Uzbek.
Design direction: Apple / Meta style, liquid-glass, calm. Do not build unrequested features; confirm
when a request is ambiguous.

## Where we are (2026-11-11)

| Stage | Status |
|---|---|
| 0 Preparation (accounts, consent text, legal questions) | Doc done; user is opening accounts |
| 1 Architecture + database | **Done.** `backend/`, 82/82 tests on Postgres 16 |
| **2 Web app (PWA)** | **Next — this repo's job** |
| 3 Attendance 2.0 (phone + geofence) | Paused by the user |
| 4 Telegram bot · 5 server-side AI · 6 mobile · 7 audit · 8 pilot · 9 SaaS · 10 stores | Later |

## Decisions already made (do not reopen without the user)

- **Backend: Supabase, region Frankfurt.** Project URL and publishable key are in `.env.example`.
  Never put the `service_role`/secret key or DB password in the repo or in client code.
- **No selfies / no biometrics.** Attendance = PIN on a kiosk tablet; later phone check-in with geofence
  (only inside/outside result stored, never a route). `attendance_marks.photo_path` stays unused.
- **Login: Telegram.** Staff sign in with Telegram (see "Stage 2 plan").
- **xodim sees only own attendance.** boshliq sees own departments, rahbar sees all.
- **mehmon (guest) role stays** — read-only: structure, tasks, charter; no attendance.
- Every table has `org_id` (future multi-company sales). Security is enforced in Postgres (RLS), never
  only in the UI.

## Backend (`backend/`)

- `db/001_schema.sql` — 20 tables. `db/002_security.sql` — RLS (56 policies), triggers, RPCs.
  Both were run in the Supabase SQL editor on 2026-11-11 and verified there: `20 · 20 · 56 · 36`
  (RLS tables, tables, policies, functions).
- Roles: `members.role` ∈ rahbar | xodim | mehmon | terminal. **boshliq is derived**: a xodim whose staff
  card is `departments.head_staff_id`. `staff.is_admin` = rahbar level for a staff member.
- Policy helpers are set-returning and used as `col in (select app.view_orgs())` — keep that pattern;
  per-row function calls made a 24k-row query take 9 s (now 6 ms).
- Writes that must be audited go through RPCs only: `kiosk_punch(pin)`, `kiosk_exit(pin)`,
  `set_pin(staff, pin)`, `attendance_set(staff, day, in, out, reason)`, `acknowledge(kind, org)`,
  `my_context(org)`. There are no insert policies on attendance, acknowledgements, task_events.
- Triggers write task history and notifications (`activity`); assignees may change only status/progress.
- PINs: `private.staff_pins`, HMAC-SHA256 with per-org pepper; terminal locks 60 s after 5 wrong PINs.
- `migrate/export_to_sql.py` converts the old artifact database export into one SQL transaction
  (deterministic uuid5 ids, `legacy_id` kept, PINs recovered and re-hashed inside the DB, demo rows skipped).
- `run_tests.sh` builds a local Postgres 16, emulates Supabase auth (`db/test/auth_stub.sql` — never run
  that file on Supabase), migrates `legacy/seed.json`, runs `db/test/test_rls.py`.

## Legacy app (`legacy/`)

The current production version is a single-file claude.ai artifact built from `legacy/src` by
`legacy/build.py` (modules concatenated in file-name order; ~400 KB). It is the **UI and behaviour
reference** for stage 2: views Tuzilma (org board), Tasklar, Davomat (incl. kiosk), Dashboard, Nizom,
Sozlamalar; task modal with comments/files/history; notifications; ⌘K spotlight; 4 animated backgrounds;
day/night/auto modes; AI recommendation (`78_ai.js`). It talks to a document store (`S.db`), not SQL —
`10_db.js` is the layer to replace. Data shapes: see `legacy/seed.json`.

## Stage 2 plan (web app / PWA)

1. (Done) Schema installed and verified on Supabase.
2. App skeleton: Vite + vanilla JS or a light framework (keep the legacy look; port CSS as-is),
   `@supabase/supabase-js`, PWA manifest + service worker, deploy to Vercel or Netlify.
3. Telegram login: bot via @BotFather (token lives only in Supabase Edge Function secrets);
   Edge Function verifies the Telegram login hash, finds/creates the auth user and returns a session.
   Invite flow: rahbar creates a one-time invite for a staff card → employee opens the bot link →
   telegram id bound to that staff card (`members` row). Needs new tables (`invites`,
   `telegram_identities`) — add as `003_*.sql` with RLS and tests in `test_rls.py`.
   Check the current Supabase docs for the recommended way to mint a session from an Edge Function.
4. Replace `10_db.js` with Supabase queries + Realtime subscriptions, view by view, keeping behaviour.
5. Storage bucket for task files (private; path `<org_id>/<task_id>/<uuid>-<name>`; policies via the
   same `app.*` helpers) and move legacy files.
6. Re-run the role tests against the real project; then migrate real data (export from the artifact,
   `export_to_sql.py`, verify counts, PIN spot-check), invite staff, keep the old app read-only 2 weeks.

Model guidance from the user's plan: Sonnet for building; Opus for architecture, security, hard bugs.

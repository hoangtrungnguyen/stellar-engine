# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Plane project

**Project:** SportBuddies | **Identifier:** `SPACE` | **UUID:** `fa573b36-9bd4-4c32-8f5f-d575039e97aa`

Use this UUID with `sync.py` and the `mcp__plane__*` tools for all work item / page operations in this folder.

```bash
# Sync all docs to Plane pages
python3 ../sync.py fa573b36-9bd4-4c32-8f5f-d575039e97aa .
```

---

## What this repo is

**SportBuddies (SpB)** — a sports court booking marketplace for Ho Chi Minh City. This repository is currently a **planning and specification repo** (no application code yet). All files are Markdown docs and SQL DDL. The build commands below apply once the codebase is scaffolded.

**Launch target:** 2026-06-01 | **Budget:** 25,000,000 VND

---

## Document map — authoritative sources

| File | Is authoritative for |
|---|---|
| `business/PRD_business.md` | Product scope, out-of-scope list, success metrics |
| `business/TECHNICAL_SPEC.md` | Tech stack, architecture decisions, env vars, deployment |
| `backend_core/schema.sql` | **Single source of truth for all DB tables, indexes, RLS, triggers, pg_cron jobs** |
| `backend_core/backend_stories.md` | Django API epics and endpoint specs |
| `customer_app/customer_stories.md` | Customer app user stories (Flutter) |
| `customer_app/flow.md` | Customer app screen-by-screen happy path + edge cases |
| `owner_dashboard/owner_stories_v2.md` | Owner dashboard stories (Flutter) |
| `owner_dashboard/flow.md` | Owner dashboard screen flow |
| `web_intro/stories.md` | Marketing site stories (Next.js) |
| `a2a/agent_stories.md` | Read-only public discovery API (2 endpoints only) |
| `design/colors.md` | Color tokens (hex values + semantic usage) |
| `design/typography.md` | Font stack (Sora + Plus Jakarta Sans) + type scale |
| `design/spacing.md` | Spacing scale, border radius, shadows, motion tokens |
| `design/components.md` | Component specs per screen/story |
| `business/document.md` | Historical only — original vision, superseded by PRD |

**Do not duplicate schema in any doc other than `schema.sql`.** If a story references a table column, point to `schema.sql`.

---

## Three products + one API surface

```
Landing Page          Customer App          Owner Dashboard       A2A API
(Next.js 15)          (Flutter Web)         (Flutter Web)         (Django)
Firebase Hosting      Firebase Hosting      Firebase Hosting       Cloud Run / Fly.io
/                     app.sportbuddies.vn   owner.sportbuddies.vn /a2a/courts
/cho-chu-san                                                       /a2a/courts/{id}/slots
/dai-ly
/bong-da /cau-long /pickleball /tennis
```

All products share one **Supabase project**: Postgres + Auth + Storage + Realtime.

---

## Tech stack quick reference

| Layer | Choice |
|---|---|
| Backend API | Django 5.x + DRF (Python) |
| Database | PostgreSQL via Supabase (`supabase db push` to deploy) |
| Auth | Supabase Auth — email+password (Resend verification) + Google OAuth only. **No phone OTP, no Twilio.** |
| Realtime | Supabase Realtime WebSocket channels |
| Push notifications | Firebase Cloud Messaging (FCM) via `firebase-admin` in Django |
| Transactional email | Resend (verification, password reset only — not booking reminders) |
| Maps | Goong.io tile server + geocoding (Vietnamese alternative to Google Maps) |
| Proximity search | `earthdistance` PostgreSQL extension — requires `float8` for lat/lng columns |
| Background jobs | pg_cron (pure SQL) + Django Celery |
| Customer/Owner apps | Flutter Web (flutter_bloc ^8, supabase_flutter ^2, go_router ^14) |
| Shared Dart package | `packages/spb_core` — models, Supabase client, repos, AppColors |
| Marketing site | Next.js 15 static export (Tailwind CSS 4 + shadcn/ui) |
| Analytics | PostHog |
| Storage | Supabase Storage bucket `court-photos` |

---

## Key architectural rules

### Database
- `lat`/`lng` must be `float8` (not `numeric`) — required by `ll_to_earth()` from `earthdistance`
- Extensions install order: `cube` before `earthdistance`
- `gen_random_uuid()` is built-in since PG 13 — no `uuid-ossp` needed
- pg_cron jobs call pure SQL functions only — **no `net.http_post()` / pg_net**
- Atomic booking uses `SELECT ... FOR UPDATE NOWAIT` inside `public.create_booking()` PL/pgSQL function
- RLS is enabled on all 14 tables; service role bypasses for background jobs

### Status enums (canonical — do not invent alternatives)
| Entity | Valid statuses |
|---|---|
| `bookings.status` | `pending` → `confirmed` → `completed` / `no_show` or `cancelled` |
| `courts.status` | `pending` → `approved` (or `suspended`) |
| `slots.status` | `open` / `booked` / `blocked` / `maintenance` |

### Auth
- Both customer app and owner dashboard use **identical auth**: email+password or Google OAuth
- Email verification via Resend is required before first login (`confirm_email = true`)
- Owner dashboard is Vietnamese-only (`Locale('vi', 'VN')` fixed, no language toggle)
- Customer app supports Vi/En toggle (SPB-014)

### Flutter apps
- State management: `flutter_bloc ^8` — BLoC pattern; Cubits for simple state
- Code gen: `build_runner` + `freezed` + `json_serializable`
- Shared code lives in `packages/spb_core` (models, repos, AppColors, theme)
- Web renderer: `--web-renderer html` for both apps
- `cd apps/customer` (not `apps/mobile`) for the customer app

### A2A API
- Read-only: GET only, no writes
- Auth: Supabase anon key in `Authorization: Bearer` header
- Rate limit: 60 req/min per IP
- Returns `[]` (not 404) on empty results

---

## Design system essentials

**Colors** (always use tokens, not raw hex in new components):
- Primary CTA: `#16A34A` (green-600)
- Available map pin: `#22C55E` (green-500)
- Fully-booked pin: `#EF4444` (red-500)
- Warning/pending: `#EAB308` (yellow-500) — **not** `#f59e0b`
- Map pin shape: 32×40px teardrop, white 1.5px outline

**Typography:** Sora (headings) + Plus Jakarta Sans (body). Both have full Vietnamese glyph coverage. Load with `subsets: ['latin', 'vietnamese']`.

**Spacing:** 4px base unit. All spacing is a multiple of 4.

---

## Sports covered (5 — not just pickleball)

`football` (5v5, 7v7) · `badminton` · `pickleball` · `tennis` · `multi` (Đa năng)

Column name in DB: `sport_types text[]` — query with `sport_types @> ARRAY['football']`

---

## Build commands (once codebase is scaffolded)

```bash
# DB migrations
supabase db push
supabase db seed

# Marketing site (Next.js)
cd apps/landing && npm install && npm run dev
cd apps/landing && npm run build           # outputs to out/ for Firebase Hosting

# Customer app (Flutter)
cd apps/customer
flutter pub get
flutter run --dart-define=SUPABASE_URL=http://localhost:54321 \
            --dart-define=SUPABASE_ANON_KEY=<local-anon-key> \
            --dart-define=GOONG_MAP_KEY=<key>
flutter build web --web-renderer html --release

# Owner dashboard (Flutter)
cd apps/owner_web
flutter pub get
flutter run -d chrome --dart-define-from-file=.env.local
flutter build web --web-renderer html --release

# Backend API (Django)
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Deploy all Firebase Hosting targets
firebase deploy --only hosting
```

---

## What is out of scope for v1

Do not implement or plan for: online payment, in-app chat, ratings/reviews, native iOS/Android apps (web PWA only), phone OTP/Twilio/SMS, agent self-service dashboard, multiple cities, AI suggestions, group bookings, tournament organisation.

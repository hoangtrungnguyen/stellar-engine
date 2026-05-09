# SportBuddies (SpB) — Technical Specification

**Version:** 1.0
**Date:** 2026-04-29
**Stack decision date:** 2026-04-29
**Launch target:** 2026-06-01

---

## 1. Architecture Overview

Three separate applications sharing one Supabase backend (Postgres + Auth + Storage + Realtime).

```
┌─────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│  Landing Page   │    │   Customer App       │    │   Owner Dashboard    │
│  (Next.js 15)   │    │   (Flutter Web)      │    │   (Flutter Web)      │
│  Firebase Host  │    │   Firebase Hosting   │    │   Firebase Hosting   │
└────────┬────────┘    └──────────┬───────────┘    └──────────┬───────────┘
         │                        │                            │
         └────────────────────────┴────────────────────────────┘
                                  │
                     ┌────────────▼────────────┐
                     │      Supabase           │
                     │  Postgres (DB)          │
                     │  Auth (Google + OTP)    │
                     │  Storage (photos)       │
                     │  Edge Functions (hooks) │
                     └─────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
         ┌────▼────┐         ┌────▼────┐        ┌────▼────┐
         │ Resend  │         │ Goong   │        │PostHog  │
         │ (email) │         │ (maps)  │        │(analytics│
         └─────────┘         └─────────┘        └─────────┘
```

---

## 2. Monorepo Structure

```
sportbuddies/
├── apps/
│   ├── landing/                 # Next.js 15 — public marketing site
│   ├── customer/                # Flutter Web — customer app (mobile post-launch)
│   └── owner_web/               # Flutter Web — owner dashboard
├── packages/
│   └── spb_core/                # Dart package: models, Supabase client, shared logic
├── supabase/
│   ├── migrations/              # SQL migration files
│   ├── seed.sql                 # Dev seed data
│   └── functions/               # Edge functions (post-booking webhook, etc.)
├── .env.example
└── README.md
```

---

## 3. Tech Stack

### 3.1 Landing Page (`apps/landing`)

| Layer | Choice | Notes |
|---|---|---|
| Framework | Next.js 15 (App Router) | Static export (`output: "export"`) |
| Styling | Tailwind CSS 4 + shadcn/ui | |
| Hosting | **Firebase Hosting** | Free tier, same project as apps |
| Analytics | PostHog JS SDK | |
| Email capture | Supabase DB (leads table) | Owner waitlist form |

> `next.config.js` must set `output: "export"` — Firebase Hosting serves static files only, no Node.js runtime.

### 3.2 Customer App (`apps/customer`)

**v1: Flutter Web** — deployed to Firebase Hosting, accessed via browser on mobile + desktop.
**Post-launch:** compile same codebase to Android APK + iOS IPA for store submission.

| Layer | Choice | Notes |
|---|---|---|
| Framework | Flutter 3.27+ | Dart 3.6+ |
| Web renderer | `--web-renderer html` | Smaller bundle, better mobile browser perf |
| State management | flutter_bloc ^8 | BLoC pattern; Cubits for simple state |
| Supabase | `supabase_flutter ^2` | Auth + DB + Storage |
| Maps | `flutter_map ^7` + Goong tile server | OSM-compatible tiles via Goong |
| Navigation | `go_router ^14` | |
| Local storage | `shared_preferences` | Cache auth session |
| Image | `cached_network_image` | |
| Analytics | PostHog Flutter SDK | |
| Code gen | `build_runner` + `freezed` + `json_serializable` | |
| Hosting | **Firebase Hosting** | |

### 3.3 Owner Dashboard (`apps/owner_web`)

| Layer | Choice | Notes |
|---|---|---|
| Framework | Flutter Web 3.27+ | Same codebase pattern as customer app |
| Web renderer | `--web-renderer html` | Better desktop browser perf |
| State management | flutter_bloc ^8 | BLoC pattern; Cubits for simple state |
| Supabase | `supabase_flutter ^2` | |
| Maps | `flutter_map ^7` (court pin only) | |
| Calendar | `table_calendar ^3` | Slot grid view |
| Hosting | **Firebase Hosting** | |

### 3.4 Shared Dart Package (`packages/spb_core`)

Shared between `mobile` and `owner_web`:
- Supabase client singleton
- All model classes (`Court`, `Slot`, `Booking`, `User`) with `freezed`
- Repository classes (CourtRepo, BookingRepo, SlotRepo)
- Constants (booking status enums, sport types, etc.)

---

## 4. Database Schema

> **Canonical source:** [`backend_core/schema.sql`](../backend_core/schema.sql)
> 
> All table DDL, indexes, and RLS policies live in `schema.sql` and are deployed via `supabase db push`. Do not maintain a duplicate schema in this document — it will drift.

### 4.1 Tables (overview)

| Table | Purpose |
|---|---|
| `users` | Mirrors `auth.users`; role: `player` / `owner` / `agent` / `admin` |
| `courts` | Sports facilities; status: `pending` / `approved` / `suspended` |
| `recurrence_rules` | Owner-defined weekly schedule patterns |
| `slots` | Bookable time windows; status: `open` / `booked` / `blocked` / `maintenance` |
| `bookings` | Reservations; status: `pending` / `confirmed` / `cancelled` / `completed` / `no_show` |
| `slot_participants` | Confirmed players in open-access slots (play-together) |
| `slot_join_requests` | Pending join requests on open-access slots |
| `notifications` | In-app notification feed |
| `skill_ratings` | Owner-assigned skill ratings per player per sport |
| `slot_push_log` | Rate-limit log for last-minute push notifications |
| `leads` | Court owner sign-up leads from `/cho-chu-san` |
| `agent_applications` | Agent registrations from `/dai-ly` |
| `commission_rules` | Configurable commission rate (200,000 VND default) |
| `commission_payouts` | Audit trail of monthly agent payouts |

### 4.2 Indexes (overview)

Proximity search uses `earthdistance` extension on `courts(lat, lng)` (float8). All foreign keys are indexed. Composite indexes optimised for cron queries (`bookings(status, reminder_sent)` partial index).

---

## 5. Row-Level Security (RLS)

> **Canonical source:** [`backend_core/schema.sql`](../backend_core/schema.sql) section 3.

All 14 tables have RLS enabled. Key policies:
- `courts`: public reads `status = approved`; owner has full access on own rows
- `slots`: public reads `status IN ('open', 'booked')` on approved courts; owner has full access on own court slots
- `bookings`: player reads/inserts own; owner reads/updates bookings on own courts; player can cancel own pending bookings only
- `notifications`: owner reads/updates own only
- `leads` / `agent_applications`: anonymous insert (landing forms); service role reads
- `commission_payouts`: agent reads own payouts only

---

## 6. Booking State Machine

```
                         cancel (player, status=pending)
    ┌────────────────────────────────────────────────────┐
    │                                                    ▼
pending ──[owner: confirm]──▶ confirmed ──[auto]──▶ completed
    │                              │
    └──[owner: cancel]──▶          └──[auto: no-show]──▶ no_show
             ▼
          cancelled ◀──[player: cancel, ≤2h before slot]── confirmed
```

Canonical status values: `pending` · `confirmed` · `cancelled` · `completed` · `no_show`

- `confirmed` — owner approved the booking
- `cancelled` — owner rejected OR player cancelled (≤2h before, or while still pending)
- `no_show` — slot end passed, player never showed (set by cron BS-091)
- `completed` — slot end passed, booking fulfilled (set by cron BS-091)

**Atomic slot reservation:** Implemented as the `public.create_booking()` PL/pgSQL function in `schema.sql` section 4.3. It uses `SELECT ... FOR UPDATE NOWAIT` to lock the slot row and fail fast on contention, then inserts the booking and updates slot status in the same transaction. Concurrent calls for the same slot: exactly one succeeds, the rest get `slot_unavailable`.

---

## 7. Authentication

| Method | Used by | Provider | Notes |
|---|---|---|---|
| Google OAuth (Gmail) | Customer app + Owner dashboard | Supabase Auth → Google Cloud | Email auto-verified |
| Email + password | Customer app + Owner dashboard | Supabase Auth → Resend | Verification email required before first login; "Forgot password" sends reset email |

**No SMS / phone OTP.** Twilio is not used. All transactional emails (verification, password reset, booking confirmations) flow through Resend.

On sign-up, a Supabase trigger inserts a row into `public.users`:

```sql
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.users (id, email, phone)
  values (new.id, new.email, new.phone);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();
```

---

## 8. Maps Integration (Goong.io)

**Customer app (Flutter):**
```yaml
# pubspec.yaml
flutter_map: ^7.0.0
latlong2: ^0.9.1
```

Goong tile URL: `https://tiles.goong.io/assets/goong_map_web.json?api_key={KEY}`
Use `TileLayer` with `urlTemplate`.

Marker colors:
- Green `#22c55e` → court has ≥ 1 open slot today
- Red `#ef4444` → fully booked or no slots today
- Yellow `#f59e0b` → 1–2 slots remaining

Proximity query (find courts within radius): use PostGIS `earth_distance` or Supabase's built-in geo functions. Pass `lat`, `lng`, `radius_km` as params to an RPC.

---

## 9. Notifications

**Email (Resend):**
- Owner: new booking received
- User: booking approved / rejected

```typescript
// Supabase Edge Function: on booking insert
await resend.emails.send({
  from: 'noreply@sportbuddies.vn',
  to: owner.email,
  subject: `Đặt sân mới: ${court.name}`,
  html: bookingEmailTemplate(booking, user, court),
});
```

**In-app:** Insert row into `notifications` table → Flutter app subscribes via Supabase Realtime channel on `notifications` filtered by `user_id = auth.uid()`.

---

## 10. File Uploads (Court Photos)

Storage bucket: `court-photos` (public read, authenticated write).

Upload flow:
1. Flutter picks image (image_picker)
2. Compress to max 1200px, 85% quality (flutter_image_compress)
3. Upload to `court-photos/{court_id}/{uuid}.jpg`
4. Append public URL to `courts.photos[]`

Max 5 photos per court. Max 2MB each after compression.

---

## 11. Flutter App Structure

Both Flutter apps follow the same pattern:

```
lib/
├── main.dart
├── app.dart                     # MaterialApp + GoRouter setup
├── core/
│   ├── supabase_client.dart     # Singleton init
│   ├── router.dart              # Route definitions
│   └── theme.dart               # Brand colors + typography
├── features/
│   ├── auth/
│   │   ├── data/                # AuthRepository
│   │   ├── bloc/                # AuthBloc / AuthCubit + AuthState
│   │   └── presentation/        # LoginScreen, OTPScreen
│   ├── courts/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/        # MapScreen, CourtDetailScreen
│   ├── bookings/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/        # BookingFlowScreen, MyBookingsScreen
│   └── profile/
└── shared/
    ├── widgets/                 # SpbButton, CourtCard, SlotTile, etc.
    └── utils/
```

---

## 12. Environment Variables

```bash
# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=        # Django backend only, never in Flutter

# Goong
GOONG_MAP_KEY=
GOONG_API_KEY=

# Resend
RESEND_API_KEY=

# PostHog
POSTHOG_KEY=
POSTHOG_HOST=https://app.posthog.com

# Flutter (via --dart-define or .env)
FLUTTER_SUPABASE_URL=
FLUTTER_SUPABASE_ANON_KEY=
FLUTTER_GOONG_MAP_KEY=
```

Flutter receives env vars via `--dart-define` at build time. Never commit secrets.

---

## 13. Deployment

All three web products deploy via **Firebase Hosting** — one project, three sites.

### firebase.json
```json
{
  "hosting": [
    { "target": "landing",  "public": "apps/landing/out" },
    { "target": "customer", "public": "apps/customer/build/web" },
    { "target": "owner",    "public": "apps/owner_web/build/web" }
  ]
}
```

### Build + deploy commands

```bash
# Build all three
cd apps/landing   && npm run build                           # outputs to out/
cd apps/customer  && flutter build web --web-renderer html --release
cd apps/owner_web && flutter build web --web-renderer html --release

# Deploy all at once
firebase deploy --only hosting
```

| App | Platform | Post-launch mobile |
|---|---|---|
| Landing (Next.js) | Firebase Hosting | — |
| Customer app (Flutter Web) | Firebase Hosting | Play Store + App Store (same codebase) |
| Owner dashboard (Flutter Web) | Firebase Hosting | — |
| Supabase migrations | Supabase CLI — `supabase db push` | — |
| Backend API (Django) | Cloud Run / Fly.io — `gunicorn` | — |

---

## 14. Performance Requirements

| Metric | Target |
|---|---|
| Map view interactive (4G mid-range Android) | < 3s |
| Court detail load (photos) | < 2s on WiFi |
| Booking confirmation (DB round-trip) | < 1s |
| Owner inbox load | < 1.5s |
| Flutter app cold start | < 2s |
| Lighthouse score — landing page | ≥ 90 (Performance, Accessibility) |

---

## 15. Security Checklist

- [ ] All user input sanitized before DB insert (Supabase parameterised queries — auto)
- [ ] RLS enabled and tested on all tables
- [ ] Owner phone number stored in `users.phone` — only revealed in booking payload after status = `confirmed` (not in listing queries)
- [ ] Service role key never bundled in Flutter app
- [ ] `FLUTTER_SUPABASE_ANON_KEY` is public by design — anon key + RLS = safe
- [ ] Supabase Storage bucket policies: public read on `court-photos`, authenticated write only
- [ ] Court status must be `approved` before appearing in map queries
- [ ] Admin role required for court approval (service role Edge Function, not client-side)
- [ ] Rate limit signup + password-reset endpoints via Supabase Auth settings (max 5 attempts/hour per email)
- [ ] Email verification required before first login (Supabase Auth setting `confirm_email = true`)

---

## 16. Local Dev Setup

```bash
# Prerequisites: Flutter 3.27+, Node 20+, Supabase CLI, Docker

# 1. Clone and install
git clone https://github.com/yourorg/sportbuddies
cd sportbuddies

# 2. Start local Supabase
supabase start

# 3. Run migrations + seed
supabase db push
supabase db seed

# 4. Landing page
cd apps/landing && npm install && npm run dev

# 5. Customer app
cd apps/customer
flutter pub get
flutter run --dart-define=SUPABASE_URL=http://localhost:54321 \
            --dart-define=SUPABASE_ANON_KEY=<local-anon-key> \
            --dart-define=GOONG_MAP_KEY=<key>

# 6. Owner dashboard
cd apps/owner_web
flutter pub get
flutter run -d chrome --dart-define-from-file=.env.local
```

---

## 17. Key Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Single Supabase project | Yes | Simpler ops; RLS handles multi-tenant isolation |
| Flutter for both apps | Yes | One language, shared `spb_core` package, Claude Code generates Dart well |
| Supabase Realtime for live updates | Built-in over websockets | Owner inbox + slot pin colors + booking auto-advance use Realtime channels; no custom websocket infra |
| No online payment v1 | Cash at venue | Removes KYC, payment provider integration, refund logic — ship faster |
| Atomic booking via DB function | `create_booking()` RPC | Prevents double-booking without application-level locking |
| Goong.io over Google Maps | Goong | VN-native, cheaper, same API surface for tile + geocoding |
| Monorepo | Yes | Shared types, single CI pipeline, easier to keep DB schema in sync |

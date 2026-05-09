# Backend Core — Epics & User Stories

**Service:** `spb_core` — Python REST API  
**Stack:** Django 5.x + Django REST Framework + Python 3.12 · PostgreSQL (Supabase) · Supabase Realtime (websockets) · Firebase Cloud Messaging (push notifications + reminders) · Resend (email — verification, password reset, transactional) · Google Maps API (geocoding/distance)  
**Auth model:** Supabase Auth issues JWTs; Django validates them via `python-jose` + Supabase JWKS  
**Build window:** May 4–22, 2026

**Priority legend:** `M` = MUST (blocks launch) · `S` = SHOULD (launch is worse without it)

---

## EPIC-B0: Infrastructure & Database Schema
*Everything else depends on this. Ship Day 1.*  
**Target: May 4**

### BS-001 — PostgreSQL schema & migrations · `M` · `0.5d`
Define and migrate all core tables.

**Tables:**
```sql
users           (id uuid PK, phone, email, full_name, avatar_url, role: owner|player, created_at)
courts          (id, owner_id→users, name, sport_types text[], capacity int, price_per_hour numeric,
                 operating_hours jsonb, address, lat numeric, lng numeric, status: pending|approved|suspended,
                 amenities text[], description, photos text[], created_at)
slots           (id, court_id→courts, start_at timestamptz, end_at timestamptz,
                 status: open|booked|blocked|maintenance, access_policy: private|open,
                 max_players int, blocked_reason text, is_recurring bool, recurrence_rule_id uuid)
recurrence_rules(id, court_id, days_of_week int[], start_time time, end_time time,
                 valid_from date, valid_until date, created_by uuid)
bookings        (id, slot_id→slots, user_id→users, court_id→courts, customer_name, customer_phone,
                 notes, status: pending|confirmed|cancelled|completed,
                 price_per_hour numeric, duration_minutes int, total_price numeric,
                 is_owner_slot bool, is_walk_in bool, override_reason text, created_at)
slot_participants(id, slot_id, user_id, joined_at, payment_status: paid|unpaid|partial,
                  payment_method: cash|transfer|app_wallet)
slot_join_requests(id, slot_id, user_id, status: pending|approved|rejected, requested_at)
notifications   (id, user_id, type, title, body, data jsonb, read bool, created_at,
                 related_booking_id, related_slot_id)
skill_ratings   (id, player_id→users, sport text, level: beginner|intermediate|advanced|professional,
                 rated_by uuid, rated_at timestamptz)
```

**Acceptance Criteria:**
- Alembic manages all migrations; `alembic upgrade head` idempotent
- Foreign keys enforced; cascades defined
- Indexes: `slots(court_id, start_at, status)`, `bookings(slot_id, status)`, `bookings(user_id)`, `courts(owner_id)`, `courts(lat, lng)`, `notifications(user_id, read)`
- `updated_at` trigger on `bookings`, `slots`, `courts`

---

### BS-002 — Row-Level Security policies · `M` · `0.5d`
All data access enforced at DB level.

**Acceptance Criteria:**
- `courts`: SELECT public for `status = approved`; INSERT/UPDATE/DELETE only `owner_id = auth.uid()`
- `slots`: SELECT public; INSERT/UPDATE only court's owner
- `bookings`: SELECT by booking owner OR court owner; INSERT by authenticated player; UPDATE status by court owner
- `notifications`: SELECT/UPDATE only `user_id = auth.uid()`
- `skill_ratings`: INSERT/UPDATE only `rated_by` is a court owner of a court the player has visited
- `slot_participants`: SELECT by slot owner or participant; INSERT by slot owner
- RLS enabled on all tables; service-role key bypasses RLS for background jobs only

---

### BS-003 — Django project scaffold · `M` · `0.5d`
Baseline app structure.

**Acceptance Criteria:**
- Project layout: `spb_core/{settings,urls}/` + Django apps: `courts`, `bookings`, `auth_ext`, `notifications`, `analytics`
- `settings/base.py` loads env vars via `django-environ`; `settings/local.py` + `settings/prod.py` split
- `auth_ext/middleware.py` — JWT decode + role extraction; attaches user to `request.user`; uses `python-jose` + Supabase JWKS
- Django ORM connects to Supabase PostgreSQL via connection pooler (port 6543); `CONN_MAX_AGE=60`
- DRF `DEFAULT_AUTHENTICATION_CLASSES` set to custom `SupabaseJWTAuthentication`
- DRF `DEFAULT_PERMISSION_CLASSES` = `IsAuthenticated`
- Health check `GET /health` returns `{status: ok, db: ok, realtime: ok}`
- Dockerfile (gunicorn) + `docker-compose.yml` for local dev
- Required env vars documented in `.env.example`

---

## EPIC-B1: Authentication & Authorization
*EPIC-2 in build plan.*  
**Target: May 4–5**

### BS-010 — Owner email/password auth · `M` · `0.5d`
*Surfaces for US-00.*

**Acceptance Criteria:**
- `POST /auth/owner/login` — calls Supabase Auth `signInWithPassword`; returns `{access_token, refresh_token, user}`
- Validates `users.role = owner`; rejects with `403` if role mismatch
- Failed login returns generic `401 Invalid credentials` (no field discrimination)
- `POST /auth/owner/forgot-password` — triggers Supabase password reset; Resend delivers the email
- Token refresh: `POST /auth/refresh` — exchanges refresh token via Supabase

---

### BS-011 — Player email + password auth · `M` · `1d`
*Surfaces for SPB-010.*

**Acceptance Criteria:**
- `POST /auth/player/signup` — calls Supabase Auth `signUp(email, password)`; password validated: min 8 chars, ≥1 letter + ≥1 digit
- Supabase Auth automatically sends a verification email via Resend (configured in Supabase dashboard) — link points to app's `/auth/callback`
- User cannot log in until `auth.users.email_confirmed_at IS NOT NULL`; attempted login on unconfirmed account returns `403 email_not_verified`
- `POST /auth/player/login` — calls Supabase Auth `signInWithPassword`; returns `{access_token, refresh_token, user}`
- Validates `users.role = player`; rejects with `403` if role mismatch
- Failed login returns generic `401 Invalid credentials` (no field discrimination)
- `POST /auth/player/forgot-password` — calls Supabase Auth `resetPasswordForEmail`; Resend delivers the reset email
- `POST /auth/player/resend-verification` — re-sends verification email; rate limit 1/min per email
- Token refresh: `POST /auth/refresh` — exchanges refresh token via Supabase
- On first successful login: auto-creates `users` row with `role = player` (via `handle_new_user` trigger)

---

### BS-012 — Player Google OAuth · `M` · `0.5d`
*Surfaces for SPB-011.*

**Acceptance Criteria:**
- `GET /auth/player/google` — redirects to Supabase Google OAuth flow
- `GET /auth/callback` — handles OAuth redirect; upserts `users` row; returns tokens
- Merges by email if user exists with a different provider

---

### BS-013 — Auth middleware & role guards · `M` · `0.5d`

**Acceptance Criteria:**
- `get_current_user` DRF authentication class: decodes JWT, fetches user from DB, attaches to `request.user`
- `IsOwner` / `IsPlayer` DRF permission classes; return `403` on role mismatch
- `IsCourtOwner(court_id)` — verifies `courts.owner_id = current_user.id`; use on all court-scoped mutations

---

### BS-014 — Player profile CRUD · `S` · `0.5d`
*Surfaces for SPB-012.*

**Acceptance Criteria:**
- `GET /players/me` — returns current player profile
- `PATCH /players/me` — updates `full_name`
- `POST /players/me/avatar` — uploads JPEG/PNG (max 2 MB) to Supabase Storage; updates `avatar_url`
- Returns `400` for files > 2 MB or wrong MIME type

---

## EPIC-B2: Court & Slot Management
*EPIC-1 + EPIC-8 in build plan.*  
**Target: May 4–5 (courts), May 12–14 (slots)**

### BS-020 — Court CRUD · `M` · `1d`
*Surfaces for US-01.*

**Acceptance Criteria:**
- `POST /courts` — creates court; accepts `name, sport_types[], capacity, price_per_hour, operating_hours, address`
- `operating_hours` schema: `{mon: {open: "06:00", close: "22:00"}, ...}`
- On create: calls Google Maps Geocoding API to resolve `address → (lat, lng)`; stored on court
- `GET /courts/{id}` — public; returns full court detail + photos
- `PATCH /courts/{id}` — owner only; partial update
- `DELETE /courts/{id}` — sets `status = suspended`; does not delete; returns `409` if active bookings exist
- `GET /courts` — paginated; filters: `owner_id`, `sport_type`, `status`

---

### BS-021 — Slot generation — manual · `M` · `0.5d`
*Surfaces for US-07, US-08, US-12.*

**Acceptance Criteria:**
- `POST /slots` — owner creates a slot: `{court_id, start_at, end_at, status}`
- Validates `start_at` and `end_at` are within court's `operating_hours`
- Validates no overlapping slot exists for same court (`409 Slot conflict`)
- Owner slots: `{is_owner_slot: true}` → status `blocked`, skips payment flow

---

### BS-022 — Slot block / unblock · `M` · `0.5d`
*Surfaces for US-12b.*

**Acceptance Criteria:**
- `PATCH /slots/{id}/block` — sets `status = blocked`, stores `blocked_reason`; returns `409` if `status = booked`
- `PATCH /slots/{id}/unblock` — sets `status = open`
- Supabase Realtime broadcasts the slot row change automatically to subscribed clients

---

### BS-023 — Recurring schedule generation · `S` · `1.5d`
*Surfaces for US-13.*

**Acceptance Criteria:**
- `POST /courts/{id}/recurrence` — saves `recurrence_rules` row; triggers slot generation
- Generates slots for next 4 weeks from `valid_from`
- Skips dates where `slots` already exist (no overwrite)
- Response includes `{created: N, skipped: N, conflicts: [{date, reason}]}`
- Django management command `generate_slots` handles generation; endpoint returns immediate 202 and triggers it via `threading.Thread`
- `DELETE /courts/{id}/recurrence/{rule_id}` — deactivates rule; does not delete existing slots

---

### BS-024 — Weekly schedule query · `M` · `0.5d`
*Surfaces for US-12, SPB-041, SPB-045.*

**Acceptance Criteria:**
- `GET /courts/{id}/slots?from=DATE&to=DATE` — returns all slots in range with status
- `GET /sports-centers/{id}/schedule?date=DATE` — returns all courts + their slots for that day (used by SPB-045 grid)
- Response includes `status`, `booking_id` (if booked), `blocked_reason` (if blocked)

---

## EPIC-B3: Booking Engine
*EPIC-7 + EPIC-8 in build plan.*  
**Target: May 8–14**

### BS-030 — Atomic booking RPC · `M` · `1d`
*Surfaces for SPB-043. Most critical path item.*

**Acceptance Criteria:**
- `POST /bookings` — wraps slot reservation in a Postgres transaction:
  1. `SELECT ... FOR UPDATE` on `slots` row
  2. If `status != open` → rollback, return `409 Slot unavailable`
  3. Insert `bookings` row with `status = pending`
  4. Update `slots.status = booked`
  5. Commit
- Concurrent requests for the same slot: exactly one succeeds, rest get `409`
- Inserts owner notification row (see BS-051)
- Supabase Realtime broadcasts slot row change to subscribed clients automatically

---

### BS-031 — Manual / walk-in booking · `M` · `0.5d`
*Surfaces for US-08, US-09, US-10.*

**Acceptance Criteria:**
- `POST /bookings/manual` — owner-only endpoint; fields: `court_id, date, start_time, end_time, customer_name, customer_phone, notes, price_per_hour_override`
- Auto-creates slot if none exists for that window; validates no conflict
- `price_per_hour` uses override if provided, else court default
- Booking status set directly to `confirmed` (no pending state for walk-ins)
- Phone validated if provided: E.164 format

---

### BS-032 — Booking status transitions · `M` · `0.5d`
*Surfaces for US-15, US-16, SPB-052.*

**Acceptance Criteria:**
- `PATCH /bookings/{id}/confirm` — owner only; `status → confirmed`; reveals `customer_phone` in response; notifies player (BS-051)
- `PATCH /bookings/{id}/reject` — owner only; `status → cancelled`; `slots.status → open`; notifies player with optional reason
- `PATCH /bookings/{id}/cancel` — player only; `status = pending` required; `status → cancelled`; `slots.status → open`; notifies owner
- All transitions: Supabase Realtime broadcasts booking row change to subscribed clients; undo token returned in response (30s grace window)
- `POST /bookings/{id}/undo` — reverts last status transition within grace period

---

### BS-033 — Booking list, search & detail · `M` · `0.5d`
*Surfaces for US-14, US-27, SPB-050, SPB-051.*

**Acceptance Criteria:**
- `GET /bookings?date=DATE&court_id=&status=&q=&page=&limit=` — owner: scoped to `courts.owner_id`; player: scoped to `user_id`
- `q` param triggers full-text search: `WHERE (customer_name ILIKE %q% OR customer_phone ILIKE %q% OR id::text ILIKE %q%)`
- `q` and `date` are mutually exclusive — when `q` is provided, date filter is ignored and all dates are searched
- `q` minimum length: 2 characters; returns `400` if shorter
- Search results sorted by `created_at DESC` (most recent first); normal list sorted by `start_at ASC`
- Default page size 20; max 100
- Summary bar fields: `total_count, pending_count, expected_revenue` (omitted when `q` is active)
- `GET /bookings/{id}` — full detail; `customer_phone` hidden for owner if `status = pending`

---

### BS-034 — Play-together access control · `S` · `0.5d`
*Surfaces for SPB-046, SPB-053, SPB-054.*

**Acceptance Criteria:**
- `PATCH /slots/{id}/access` — booking owner sets `access_policy` and `max_players`
- `POST /slots/{id}/join` — player requests to join open slot; creates `slot_join_requests` row
- `PATCH /slot-join-requests/{id}/approve` — slot owner approves; inserts `slot_participants` row
- `PATCH /slot-join-requests/{id}/reject` — sets request `status = rejected`; notifies requester
- `GET /slots/{id}/participants` — lists all confirmed participants + join requests for slot owner

---

### BS-035 — Price calculation service · `M` · `0.5d`
*Surfaces for US-09, US-10.*

**Acceptance Criteria:**
- `GET /bookings/price-estimate?court_id=&start_at=&end_at=&price_override=` — returns `{duration_minutes, base_price, override_price, total}`
- Duration computed as `(end_at - start_at)` in minutes; rounded to nearest 30
- Used by both manual booking form (live update) and booking wizard

---

## EPIC-B4: Realtime Layer (Supabase Realtime)
*Underpins SPB-043 step 2 auto-advance, US-28 notification badge, slot pin colors.*  
**Target: May 8–10**

Supabase Realtime broadcasts Postgres row changes (INSERT/UPDATE/DELETE) to subscribed Flutter clients over websockets. No separate sync service needed — the Django API writes to Postgres; Realtime handles delivery automatically.

### BS-040 — Supabase Realtime: slot availability · `M` · `0.5d`
*Enables SPB-031 pin color updates.*

**Acceptance Criteria:**
- Enable Realtime on `slots` table in Supabase dashboard (publication: `supabase_realtime`)
- Customer app subscribes: `supabase.from('slots').on('UPDATE', handler).filter('court_id', 'in', nearbyCourtIds).subscribe()`
- Handler updates pin color when `slots.status` changes (open → booked, booked → open)
- Subscription scoped to nearby courts only (list refreshed when map moves)
- RLS ensures client only receives rows for `status IN (open, booked)` on `approved` courts

---

### BS-041 — Supabase Realtime: booking status · `M` · `0.5d`
*Enables SPB-044 auto-advance to Step 3.*

**Acceptance Criteria:**
- Enable Realtime on `bookings` table
- Player app subscribes: `supabase.from('bookings').on('UPDATE', handler).eq('id', bookingId).subscribe()`
- Handler auto-advances booking wizard when `status → confirmed`
- Subscription created after RPC succeeds in BS-030; cancelled on wizard exit

---

### BS-042 — Supabase Realtime: notifications · `M` · `0.5d`
*Enables US-28 realtime badge.*

**Acceptance Criteria:**
- Enable Realtime on `notifications` table
- Client subscribes: `supabase.from('notifications').on('INSERT', handler).eq('user_id', authUid).subscribe()`
- Handler increments unread badge count; toasts notification message
- On notification centre open: `read_at` updated; badge clears

---

## EPIC-B5: Notification System
*EPIC-10 in build plan.*  
**Target: May 8–11 (in-app), May 19–21 (SMS/push)**

### BS-050 — FCM device token registration · `M` · `0.5d`

**Acceptance Criteria:**
- `POST /users/me/fcm-token` — stores FCM registration token against user
- `DELETE /users/me/fcm-token` — removes token on logout
- Tokens stored in `users.fcm_tokens text[]` (supports multiple devices)

---

### BS-051 — In-app notification dispatch · `M` · `1d`
*Surfaces for US-15, US-16, US-28, SPB-090.*

**Notification events and recipients:**

| Event | Recipient | Message |
|---|---|---|
| Booking created (pending) | Owner | "Yêu cầu đặt sân mới từ [name]" |
| Booking confirmed | Player | "Đặt sân thành công — [court] lúc [time]" |
| Booking rejected | Player | "Đặt sân bị từ chối — [reason]" |
| Booking cancelled by player | Owner | "[name] đã huỷ đặt sân lúc [time]" |
| Join request approved | Requester | "Yêu cầu tham gia đã được chấp nhận" |
| Join request rejected | Requester | "Yêu cầu tham gia bị từ chối" |

**Acceptance Criteria:**
- `notifications` row inserted in Postgres
- Supabase Realtime broadcasts notification row to client subscribed on `notifications` filtered by `user_id`
- FCM `send_multicast` to all `users.fcm_tokens` for recipient (handles offline/background delivery)
- `GET /notifications?page=&limit=` — paginated, newest first
- `PATCH /notifications/{id}/read` — marks single read
- `POST /notifications/read-all` — marks all read for current user

---

### BS-052 — Push booking reminder · `S` · `1d`
*Surfaces for SPB-092.*

**Acceptance Criteria:**
- pg_cron schedules `mark_reminder_candidates()` every 5 min (no-op marker; see schema.sql section 6)
- Django scheduled job (Celery beat or external cron) polls every 5 min: `SELECT * FROM bookings WHERE status='confirmed' AND reminder_sent=false AND start_at BETWEEN now()+interval '55 min' AND now()+interval '65 min'`
- For each row: send FCM push via `firebase-admin` SDK to all tokens in `users.fcm_tokens` for the player
- Notification payload: `title="Sắp đến giờ chơi"`, `body="Sân [court_name] lúc [time] — [address]"`, `data={booking_id, deep_link='/bookings/:id'}`
- Sets `bookings.reminder_sent = true` after successful send to prevent duplicates
- Players with empty `fcm_tokens` array: skipped silently, logged to PostHog `reminder_skipped_no_token`
- Failed FCM send logged; retried once; on permanent failure (`UNREGISTERED` token), token removed from `users.fcm_tokens`

---

### BS-053 — Last-minute slot push notification · `S` · `1d`
*Surfaces for SPB-093.*

**Acceptance Criteria:**
- `POST /slots/{id}/last-minute` — owner marks slot as last-minute available
- Service queries `users` where last known location within 5km of court (via `users.last_lat`, `users.last_lng`)
- Distance filter uses Haversine formula in SQL: `earth_distance(ll_to_earth(lat,lng), ll_to_earth(u_lat,u_lng)) < 5000`
- FCM multicast to matching users; deep-link data: `{screen: court_detail, court_id, slot_id}`
- Rate limit: `slot_push_log` table tracks 1 push per user per hour; skip duplicates

---

## EPIC-B6: Court Discovery & Maps
*EPIC-4 in build plan.*  
**Target: May 5–9**

### BS-060 — Nearby courts query · `M` · `1d`
*Surfaces for SPB-030, SPB-031, SPB-032, SPB-033.*

**Acceptance Criteria:**
- `GET /courts/nearby?lat=&lng=&radius_km=5&sport=&date=` — returns courts within radius
- Filters `courts.status = approved` only
- Distance calculated with `earth_distance` PostGIS extension on `(courts.lat, courts.lng)`
- Each court in response includes `has_open_slots_today: bool` (join against `slots`)
- `sport` filter: `WHERE sport_types @> ARRAY[sport]`
- Radius options: 1, 3, 5 km; default 5
- Response sorted by distance ASC
- Empty result: `[]` with `200` (client shows empty state)

---

### BS-061 — Court geocoding on create/update · `M` · `0.5d`
*Surfaces for BS-020.*

**Acceptance Criteria:**
- On `POST /courts` and `PATCH /courts/{id}` (when `address` changes): calls Google Maps Geocoding API
- Stores `lat`, `lng` on court record
- If geocoding fails: court saved with `lat = null, lng = null`; returns `207` with warning
- Geocoding result also returns `formatted_address`; stored as canonical address

---

### BS-062 — Open slot list · `S` · `0.5d`
*Surfaces for SPB-034.*

**Acceptance Criteria:**
- `GET /slots/open-for-join?lat=&lng=&radius_km=&sport=` — returns slots where `access_policy = open AND status = booked AND start_at > now()`
- Each slot includes `court_name, sport, start_at, end_at, spots_remaining` (derived from `max_players - COUNT(slot_participants)`)
- Sorted by `start_at ASC`

---

### BS-063 — Player location update · `S` · `0.5d`
*Used by BS-053 for proximity targeting.*

**Acceptance Criteria:**
- `PATCH /players/me/location` — updates `users.last_lat`, `users.last_lng`, `users.location_updated_at`
- Called by client app on map screen open
- No history stored; only current location

---

## EPIC-B7: Analytics & Reporting
*EPIC-9 in build plan.*  
**Target: May 14–15**

### BS-070 — Revenue statistics · `M` · `1d`
*Surfaces for US-02.*

**Acceptance Criteria:**
- `GET /analytics/revenue?court_id=&from=DATE&to=DATE` — returns:
  ```json
  {
    "total_estimated_revenue": 4200000,
    "total_bookings": 34,
    "confirmed_bookings": 28,
    "wow_change_pct": 12.5,
    "wow_direction": "up",
    "daily_breakdown": [
      {"date": "2026-05-05", "bookings": 5, "revenue": 600000, "occupancy_pct": 62, "status": "completed"}
    ]
  }
  ```
- Revenue = `SUM(confirmed bookings: duration_minutes/60 * price_per_hour)` for the period
- WoW trend compares current period vs same-length period prior
- Occupancy % = booked hours / total available hours per day
- `status` per day: `completed` for past dates, `pending` for today/future

---

### BS-071 — Visitor statistics · `S` · `0.5d`
*Surfaces for US-03.*

**Acceptance Criteria:**
- `GET /analytics/visitors?court_id=&from=DATE&to=DATE` — returns:
  ```json
  {
    "unique_visitors": 42,
    "total_visits": 87,
    "visit_trend_pct": 8.3,
    "hourly_density": [
      {"hour": 6, "occupancy_pct": 20}, ..., {"hour": 21, "occupancy_pct": 95}
    ],
    "peak_hours": [{"hour": 19, "occupancy_pct": 98, "rank": 1}]
  }
  ```
- Peak hours: hours where `occupancy_pct >= 90`, ranked by occupancy DESC, top 3
- Unique visitors = `COUNT(DISTINCT bookings.user_id)` for confirmed bookings

---

### BS-072 — Revenue optimization recommendation · `S` · `0.5d`
*Surfaces for US-04.*

**Acceptance Criteria:**
- `GET /analytics/recommendation?court_id=` — analyzes last 30 days of hourly occupancy
- Returns recommendation if peak pattern detected: `{peak_window: "19:00–21:00", suggested_increase_pct: 10, confidence: "high"}`
- Peak pattern = 3+ consecutive peak hours (≥90% occupancy) present in ≥70% of days in window
- Returns `{recommendation: null}` if no clear pattern
- `POST /analytics/recommendation/apply` — updates `slots.price_per_hour` override for the peak window hours

---

### BS-073 — Export report · `S` · `0.5d`
*Surfaces for US-06, US-18.*

**Acceptance Criteria:**
- `GET /analytics/export?court_id=&from=DATE&to=DATE&format=csv` — streams CSV response
- `GET /bookings/export?court_id=&date=&status=&format=csv` — streams booking list CSV
- CSV columns (bookings): `booking_id, customer_name, customer_phone, court, start_at, end_at, status, total_price`
- CSV columns (analytics): KPI summary rows + per-day breakdown
- `Content-Disposition: attachment; filename=report_YYYY-MM-DD.csv`
- PDF optional: use `weasyprint` to render HTML template; same endpoint with `format=pdf`

---

## EPIC-B8: Player & Slot Detail Management
*Epics 5–7 in build plan. Post-launch.*

### BS-080 — Slot detail — player list & payment · `S` · `0.5d`
*Surfaces for US-19, US-21.*

**Acceptance Criteria:**
- `GET /slots/{id}/players` — returns participants with `payment_status`; owner-only
- Summary: `{total_expected, total_collected, players: [{name, payment_status, payment_method}]}`
- `PATCH /slot-participants/{id}/payment` — owner marks player as paid; records `payment_method`

---

### BS-081 — Add player to slot · `S` · `0.5d`
*Surfaces for US-20.*

**Acceptance Criteria:**
- `GET /players/search?q=NAME_OR_PHONE` — owner searches existing player records
- `POST /slots/{id}/participants` — adds player by `user_id` or creates new minimal player record `{full_name, phone}`
- Exceeding `max_players`: allowed with `force: true` flag; returns `207` with capacity warning

---

### BS-082 — Player list for facility · `S` · `0.5d`
*Surfaces for US-23.*

**Acceptance Criteria:**
- `GET /owners/me/players?sport=&frequency=&q=&sort=last_visit&page=` — all players who have confirmed bookings at owner's courts
- Each player: `avatar, name, phone, sports[], skill_levels{}, total_visits, last_visit_date`
- Frequency filter: `visited_in_last_30_days`, `visited_in_last_7_days`, `never_returned`

---

### BS-083 — Player profile detail · `S` · `0.5d`
*Surfaces for US-24.*

**Acceptance Criteria:**
- `GET /players/{id}/profile` — owner-scoped; returns profile + booking history at owner's courts only
- Booking history: date, court, sport, payment_status
- Aggregates: `total_visits, total_spend, favourite_sport, favourite_hour`

---

### BS-084 — Skill rating · `S` · `0.5d`
*Surfaces for US-25.*

**Acceptance Criteria:**
- `PUT /players/{id}/skill/{sport}` — owner sets skill level; upserts `skill_ratings`; logs history
- Skill levels: `beginner | intermediate | advanced | professional`
- `GET /players/{id}/skills` — returns all sport/level pairs with rater and timestamp
- Players cannot call `PUT /players/{id}/skill/{sport}` on themselves (403)

---

## EPIC-B9: Background Jobs & Cron
**Target: May 19–22**

### BS-090 — Booking reminder cron · `S` · `0.5d`
*Surfaces for BS-052.*

**Acceptance Criteria:**
- pg_cron schedule: `*/5 * * * *` calls `select public.mark_reminder_candidates()` (SQL-only marker, no HTTP)
- Django Celery-beat job runs every 5 min independently; polls eligible bookings and sends FCM push
- Duplicate protection: `reminder_sent = true` flag set inside the same Django transaction

---

### BS-091 — Slot expiry & completion · `S` · `0.5d`

**Acceptance Criteria:**
- pg_cron schedule: `*/15 * * * *` calls pure-SQL `select public.expire_slots()` (no HTTP, no pg_net)
- Function sets `bookings.status = completed` and `slots.status = open` for slots where `end_at < now() AND status = booked AND bookings.status = confirmed`
- Pending bookings older than 24h with no owner action are auto-cancelled inside the same function call
- Supabase Realtime broadcasts slot and booking row changes to subscribed clients automatically

---

### BS-092 — Recurring slot generator cron · `S` · `0.5d`

**Acceptance Criteria:**
- Scheduled in Django (Celery beat or external cron at 02:00 ICT = 19:00 UTC); not in pg_cron because logic is too complex for a SQL-only function
- Django management command `generate_recurring_slots` extends active recurrence rules by 1 week (rolling 4-week window)
- Skips conflicts; logs `{court_id, created, skipped}` per run

---

## Build Schedule

| Epic | Stories | Est. days | Target |
|---|---|---|---|
| B0: Infrastructure & Schema | BS-001–003 | 1.5 | May 4 |
| B1: Auth & Profile | BS-010–014 | 2.5 | May 4–5 |
| B2: Court & Slot Mgmt | BS-020–024 | 3.5 | May 4–5, 12–14 |
| B3: Booking Engine | BS-030–035 | 4 | May 8–14 |
| B4: Supabase Realtime | BS-040–042 | 1.5 | May 8–10 |
| B5: Notifications | BS-050–053 | 3.5 | May 8–21 |
| B6: Court Discovery | BS-060–063 | 3 | May 5–9 |
| B7: Analytics & Reports | BS-070–073 | 3 | May 14–15 |
| B8: Player Detail (post-launch) | BS-080–084 | 2.5 | Post-launch |
| B9: Background Jobs | BS-090–092 | 1.5 | May 19–22 |
| **Total (launch scope)** | **~27** | **~22d** | **~May 22** |

**Critical path:** Schema + RLS → Django scaffold → Auth → Atomic Booking (BS-030) → Supabase Realtime → Notification Dispatch

**Runs parallel:**
- B6 (Discovery) parallel with B3 (Booking Engine) from May 9
- B7 (Analytics) parallel with B9 (Jobs) from May 14

---

## Integration Map

| Frontend story | Backend endpoint(s) |
|---|---|
| SPB-010 email/password | BS-011 `/auth/player/signup` + `/login` + `/forgot-password` |
| SPB-011 Google OAuth | BS-012 `/auth/player/google` |
| SPB-030 map screen | BS-060 `/courts/nearby` |
| SPB-031 pin colors | BS-040 Supabase Realtime `slots` subscription |
| SPB-043 atomic booking | BS-030 `POST /bookings` |
| SPB-044 waiting screen | BS-041 Supabase Realtime `bookings` subscription |
| SPB-046 play-together | BS-034 `PATCH /slots/{id}/access` |
| US-00 owner login | BS-010 `/auth/owner/login` |
| US-02 revenue KPIs | BS-070 `/analytics/revenue` |
| US-08 walk-in booking | BS-031 `POST /bookings/manual` |
| US-12 weekly schedule | BS-024 `/courts/{id}/slots` |
| US-12b block slot | BS-022 `PATCH /slots/{id}/block` |
| US-14 booking list | BS-033 `GET /bookings` |
| US-27 booking search | BS-033 `GET /bookings?q=` |
| US-15 approve booking | BS-032 `PATCH /bookings/{id}/confirm` |
| US-16 reject booking | BS-032 `PATCH /bookings/{id}/reject` |
| US-28 notification bell | BS-042 Supabase Realtime + BS-051 FCM |
| SPB-092 push reminder | BS-052 + BS-090 pg_cron + Django Celery + FCM |
| SPB-093 last-minute push | BS-053 `/slots/{id}/last-minute` |

---

*Last updated: 2026-05-06*

# Customer App — Epics & User Stories

**App:** Customer App (Flutter Web → mobile post-launch)
**Stack:** Flutter + flutter_bloc + supabase_flutter + flutter_map ^7 (Goong) + flutter_localizations + intl
**Hosting:** Firebase Hosting `customer` target
**Build window:** May 4–22, 2026

---

## EPIC-2: Authentication & Profile
*Player identity. Logic lives in `spb_core`; UI in `apps/customer`.*
**Target: May 4–5**

### SPB-010 — Email + password signup & login `M | 1d`
As a player, I want to sign up and log in with my email address and a password so I have a stable account I can recover.
- Sign-up screen: email + password (min 8 chars, ≥1 letter + ≥1 digit) + confirm-password
- On sign-up: Supabase Auth creates the auth user; verification email sent automatically via Resend with a confirmation link
- User cannot log in until email is verified — "Vui lòng kiểm tra email để xác minh tài khoản" message shown after signup
- After clicking the verification link: user redirected to app, auto-logged-in, `users` row created with `role = player`
- Login screen: email + password fields → Supabase `signInWithPassword` → returns to map screen
- Failed login returns generic `401` ("Email hoặc mật khẩu không đúng") — no field discrimination
- "Quên mật khẩu?" link sends password reset email via Resend
- Session persists across browser close (`persistSession: true` via `shared_preferences`)
- Resend verification email link available on login screen if user lost it (rate limit: 1 per minute)

### SPB-011 — Google OAuth login `M | 0.5d`
As a player, I want to log in with my Gmail account so I don't have to remember a password.
- "Tiếp tục với Google" triggers Supabase OAuth flow
- User created/merged in `users` table on first login (email auto-verified)
- Redirects back to map screen after auth
- If a player previously signed up with email+password using the same Gmail address: accounts are merged on `email` match

### SPB-012 — Profile view & edit `S | 0.5d`
As a player, I want to see and update my name and avatar so courts know who I am.
- Profile screen: `full_name`, `phone`, `avatar_url`
- Can edit `full_name`; upload avatar to Supabase Storage (max 2 MB, JPEG/PNG)

### SPB-014 — Language selection `S | 0.5d`
As a player, I want to switch the app language between Vietnamese and English so I can use it comfortably.
- Language picker in profile screen: "Tiếng Việt" (default) / "English"
- Selection persisted in `shared_preferences` (`locale` key); applied on next app start and immediately on change
- All UI strings sourced from ARB files: `lib/l10n/app_vi.arb` (default) + `lib/l10n/app_en.arb`
- Packages: `flutter_localizations` (SDK) + `intl`; `MaterialApp.localizationsDelegates` set to `AppLocalizations.delegates`
- Locale falls back to `vi` if device locale is not `vi` or `en`
- Language change does not require re-login; no server-side storage (client-only preference)

---

## EPIC-4: Court Discovery
*The map — first screen a player sees when they open the app.*
**Target: May 5–9**

### SPB-030 — Map screen `M | 1.5d`
As a player, I want to see a map of nearby courts so I know what's around me.
- Goong map renders via `flutter_map ^7` + Goong tile URL (env var `GOONG_MAP_KEY`)
- Map centers on user GPS location; falls back to HCMC center (10.776°N, 106.701°E) if permission denied
- Courts loaded from `courts` where `status = approved`

### SPB-031 — Court availability pins `M | 1d`
As a player, I want to see at a glance which courts have open slots so I skip fully booked ones.
- Green pin = ≥1 slot with `status = open` in next 24h
- Red pin = no open slots in next 24h
- Pin color updates via Supabase Realtime subscription on `slots` table

### SPB-032 — Filter by sport type `M | 0.5d`
As a player, I want to filter by sport so I only see relevant courts.
- Filter chips: Tất cả / Bóng đá / Cầu lông / Pickleball / Tennis / Đa năng
- Selecting chip re-queries courts with `sport_types @> ARRAY[sport]`

### SPB-033 — Filter by distance `S | 0.5d`
As a player, I want to filter courts within X km so I don't see courts far away.
- Quick-select: 1km / 3km / 5km (default 5km)
- Filters by Haversine distance from current location
- Empty state: "Không có sân trong khu vực này"

### SPB-034 — Open slot list tab `S | 0.5d`
As a player looking for a group game, I want a tab listing open slots so I can browse games to join without panning the map.
- Second tab on map screen: "Slot trống" alongside the map view
- Lists slots where `access_policy = open AND status = booked` ordered by `start_at ASC` (court is taken but open for group play)
- Each row: court name, sport, date/time, spots remaining vs capacity
- Tap row → slot detail screen (SPB-035)

### SPB-035 — Slot fullness indicator `S | 0.5d`
As a player, I want to see remaining spots in a slot so I know if I can still join before requesting.
- Slot detail shows participant count vs max players (e.g., "3/6 người")
- "Đã đủ người" badge disables join action when full
- Derived from `slot_participants` count vs `slots.max_players`

---

## EPIC-5: Court Detail & Booking
*The golden path — tap pin → 4-step booking wizard → confirmed reservation.*
**Target: May 9–14**

### SPB-040 — Court detail screen `M | 1d`
As a player, I want to see a court's details so I can decide if it's the right court.
- Photo carousel (Supabase Storage URLs), court name, address, sports[], price/hour, description, amenities[]
- "Đặt sân ngay" CTA visible without scrolling on mobile

### SPB-045 — Sports center schedule overview `M | 1d`
As a player, I want to see a timetable of all courts in a sports center so I can compare availability and pick the best time.
- Sports center screen accessible from map pin or court detail breadcrumb
- Grid: each row = one court; columns = time slots for the selected day
- Open slots are tappable → navigates to booking wizard (SPB-042)
- Greyed cells = booked/blocked
- Date tabs: today + next 6 days

### SPB-041 — Available slot picker `M | 1d`
As a player, I want to see available time slots so I can pick one that fits.
- Date tabs: today + next 6 days
- Each slot: start time, end time, price
- Booked/blocked slots greyed-out (unselectable)
- Fetches `slots` where `court_id = X AND status = open AND start_at >= now()`

### SPB-042 — Booking wizard — Step 1: confirm details `M | 0.5d`
As a player, I want to review court info and price before confirming so I don't make a mistake.
- Shows: court name, date, time, price breakdown
- Name + phone pre-filled from profile; editable
- "Xác nhận đặt sân" submit button → triggers SPB-043 RPC then advances to Step 2

### SPB-043 — Atomic booking via RPC `M | 1d`
As a player, I want my booking to succeed or fail cleanly so I'm never double-booked.
- Calls `create_booking(slot_id, user_id, notes)` RPC on confirm
- If slot taken: error toast "Slot vừa được đặt, chọn giờ khác" → return to slot picker
- On success: `bookings.status = pending`, `slots.status = booked`
- Loading state on button during RPC call

### SPB-044 — Booking wizard — Step 2: awaiting owner confirmation `M | 0.5d`
As a player, I want to see that my booking request was sent and is waiting for the owner so I know the next step.
- Shows: booking ID, court name, date/time, status "Chờ chủ sân xác nhận"
- Inserts notification row for owner
- Supabase Realtime listener on `bookings.status`; auto-advances to Step 3 when owner confirms
- "Về bản đồ" escape hatch always visible

### SPB-046 — Booking wizard — Step 3: play-together access control `S | 0.5d`
As a player who booked a slot, I want to control who can join my session so I can play with people I choose.
- Shown after owner confirms (`bookings.status → confirmed`)
- Toggle: "Riêng tư" (invite-only, default) or "Mở" (open — anyone can request)
- "Bỏ qua" skip button always visible; skipping defaults to "Riêng tư" and advances to Step 4
- If open: slot appears in SPB-034 slot list (`access_policy = open`); max players field required
- Saved to `slots.access_policy` and `slots.max_players`

### SPB-047 — Booking wizard — Step 4: payment `S | 0.5d`
As a player, I want to complete payment as the final booking step so my reservation is secured.
- Currently: "Thanh toán tại sân" summary screen confirming booking complete
- Shows final breakdown: court, date/time, total price, payment method
- "Nhớ mang tiền mặt" notice (prominent)
- CTAs: "Xem lịch đặt của tôi" | "Về bản đồ"

---

## EPIC-6: My Bookings
*Player's upcoming reservations and booking history.*
**Target: May 14–16**

### SPB-050 — Upcoming bookings `M | 0.5d`
As a player, I want to see upcoming bookings so I know where and when I'm playing.
- Bookings where `status IN (pending, confirmed)` ordered by `start_at ASC`
- Filter chips: Tất cả / by sport / by status
- Status badge: "Chờ xác nhận" (yellow) / "Đã xác nhận" (green)

### SPB-051 — Booking history `S | 0.5d`
As a player, I want to see past bookings so I can rebook a court I liked.
- Bookings where `status IN (completed, cancelled)` ordered by `start_at DESC`
- "Đặt lại" shortcut navigates to that court's detail screen

### SPB-052 — Cancel a pending booking `M | 0.5d`
As a player, I want to cancel a booking I no longer need so the slot is freed.
- Cancel only available for `status = pending`
- On cancel: `bookings.status → cancelled`, `slots.status → open`
- Owner receives notification of cancellation

### SPB-053 — Play-together participant management `S | 0.5d`
As a player who booked a slot, I want to see and approve people who want to join my session so I can find suitable playing partners.
- "Yêu cầu tham gia" section in booking detail showing pending join requests
- Approve or reject each request; approved → inserts row in `slot_participants`
- Full confirmed participant list visible to slot owner

### SPB-054 — Join slot request & status `S | 0.5d`
As a player, I want to request to join an open slot and track whether I'm approved so I know if I have a game.
- "Đăng ký chơi cùng" button on slot detail when `access_policy = open` and not full
- Creates `slot_join_requests` row with `status = pending`
- In My Bookings, request appears under a "Đang chờ xác nhận" section with badge: "Chờ xác nhận" / "Đã chấp nhận" / "Từ chối"

---

## EPIC-10: Player Notifications
*Real-time booking status updates for the player.*
**Target: May 19–21**

### SPB-090 — In-app notification centre `M | 0.5d`
As a player, I want to see all booking notifications so I don't miss updates.
- Bell icon with unread count badge
- List with timestamp + message; tap navigates to relevant booking
- Mark all as read clears badge

### SPB-092 — Push booking reminder `S | 1d`
As a player, I want a push notification reminder 1 hour before my court time so I don't forget.
- Backend pg_cron + Django Celery job (BS-052, BS-090) fires at T-60min for each confirmed booking
- Push via Firebase Cloud Messaging (FCM) to all `users.fcm_tokens` for the player; payload: court name, time, address; deep link to booking detail
- Only fires for `status = confirmed`; `reminder_sent = true` flag prevents duplicate sends
- If player has no FCM tokens registered (e.g. has not granted notification permission): skip silently, log for analytics

### SPB-093 — Last-minute slot push notification `S | 1d`
As a player, I want a push notification when a nearby court has a slot opening soon so I can book on the spot.
- Owner marks a slot as last-minute available (from owner dashboard)
- Django endpoint (BS-053) queries players within 5km of that court using `earth_distance(ll_to_earth(...))`
- Push via FCM: "Còn sân trống [court name] lúc [time] hôm nay — đặt ngay"
- Player taps → deep link to court detail screen with that slot pre-selected
- Max 1 push per player per hour (rate limit via `slot_push_log` table)

---

## Build Schedule

| Epic | Stories | Days | Window |
|---|---|---|---|
| EPIC-2: Auth (player) | 4 | 2.5 | May 4–5 |
| EPIC-4: Court Discovery | 6 | 4 | May 5–9 |
| EPIC-5: Court Detail & Booking | 8 | 5 | May 9–14 |
| EPIC-6: My Bookings | 5 | 2 | May 14–16 |
| EPIC-10: Notifications | 3 | 2 | May 19–21 |
| **Total** | **26** | **~15.5** | **May 22** |

**Critical path:** Auth → Map → Court Detail → Atomic Booking → Play-together Access Control

## Priority legend
- `M` = MUST (blocks launch)
- `S` = SHOULD (launch is worse without it)

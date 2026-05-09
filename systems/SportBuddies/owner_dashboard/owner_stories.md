# Owner Dashboard — User Stories v2

Sources: `owner_dashboard/draft1.html` · [Google Sheet](https://docs.google.com/spreadsheets/d/1F02HNNlFxQdiWblohV1oz5a9a1VgLrdLJG-uo1wBgxs) · `owner_dashboard/owner_stories.md`  
Persona: **Court Owner / Facility Admin** managing one or more sports courts.

**App:** Owner Dashboard (Flutter Web)  
**Stack:** Flutter + flutter_bloc ^8 + supabase_flutter + flutter_localizations + intl  
**Hosting:** Firebase Hosting `owner` target  
**Build window:** May 4–15, 2026

**Priority legend:** `M` = MUST (blocks launch) · `S` = SHOULD (launch is worse without it)

---

## Epic 0: Authentication
*EPIC-2 in build plan. Logic lives in `spb_core`; UI in `apps/owner_web`.*  
**Target: May 4–5**

### US-00b — Vietnamese as primary language · `M` · `0.5d`
**As a** court owner,  
**I want to** use the dashboard entirely in Vietnamese,  
**so that** I can manage my courts without language barriers.

**Acceptance Criteria:**
- Primary (and only) language for v1: Tiếng Việt
- All UI strings — labels, buttons, error messages, notifications, tooltips, placeholder text, date/time formats — written in Vietnamese
- Strings sourced from ARB file: `lib/l10n/app_vi.arb`; no hardcoded strings in widget code
- Packages: `flutter_localizations` (SDK) + `intl`; `MaterialApp.locale` fixed to `const Locale('vi', 'VN')`
- Date format: `dd/MM/yyyy`; time format: 24-hour (`HH:mm`); currency: `đ` suffix, thousands separator `.` (e.g. `150.000đ`)
- No language switcher in v1 — Vietnamese only; English localisation deferred to post-launch

---

### US-00 — Email/password login · SPB-013 · `M` · `0.5d`
**As a** court owner,  
**I want to** log in with my email and password,  
**so that** my dashboard is secure and my data is scoped to my facility.

**Acceptance Criteria:**
- Email/password auth via Supabase; user must have `role = owner`
- "Quên mật khẩu" sends a reset email via Resend
- Failed login shows a generic error (does not reveal which field is wrong)
- Session persists across browser close (`persistSession: true`)

---

## Epic 1: Thiết Lập (Setup)

### US-01 — Create court types
**As a** court owner,  
**I want to** create and configure the types of courts at my facility,  
**so that** the system accurately reflects my venue and players can book the right court.

**Acceptance Criteria:**
- Setup screen allows creating a court with: name, sport type, capacity, and operating hours
- Sport types available: Football, Pickleball, Tennis, Badminton, Multi-purpose, etc.
- Created courts immediately appear in the court selector across the app (booking, schedule, analytics)
- Owner can edit or deactivate an existing court type
- Deactivated courts no longer appear as bookable options but their history is preserved

---

## Epic 2: Dashboard
*EPIC-9 in build plan.*  
**Target: May 14–15**

### US-02 — View revenue statistics · SPB-080 · `M` · `1d`
    **As a** court owner,  
**I want to** see aggregated revenue metrics on the dashboard,  
**so that** I can track the financial health of my facility at a glance.

**Acceptance Criteria:**
- KPI cards: estimated revenue (confirmed count × price/hr), total bookings, confirmed bookings, week-over-week trend (% change with ↑/↓ indicator)
- Negative trends shown in red; positive in green
- Revenue broken down in a per-day table: Day/Date, bookings count, revenue (VNĐ), occupancy %, status badge
- Status badge per day: "Hoàn thành" (green) for past days; pending indicator for today/future
- Rows sorted chronologically Mon → Sun

---

### US-03 — View player visit statistics · SPB-081 · `S` · `0.5d`
**As a** court owner,  
**I want to** see statistics on how often players visit the facility,  
**so that** I can understand demand patterns and identify loyal vs. lapsed customers.

**Acceptance Criteria:**
- Dashboard shows total unique visitors and total visits for the selected period
- Visit trend shown (% change vs. previous period)
- Bar chart of hourly visit density (06:00–22:00); peak hours (≥90% occupancy) highlighted in a distinct color
- Top 3 busiest time slots highlighted with a rank badge
- Hovering/tapping a bar shows exact occupancy % tooltip

---

### US-04 — Receive a revenue optimization recommendation
**As a** court owner,  
**I want to** see a data-driven pricing suggestion based on peak visit hours,  
**so that** I can increase revenue during high-demand slots without guesswork.

**Acceptance Criteria:**
- Recommendation card surfaces automatically when a clear peak pattern is detected
- Card states the peak window and suggested price increase (e.g. "+10% from 19:00–21:00")
- "Áp dụng ngay" button applies the pricing rule or navigates to the pricing config
- Recommendation is dismissible

---

### US-05 — Filter dashboard by time period
**As a** court owner,  
**I want to** switch the dashboard between 7-day, 30-day, or a custom date range,  
**so that** I can analyze trends over different horizons.

**Acceptance Criteria:**
- Period selector (default "7 ngày qua") with options: 7 days, 30 days, custom range
- All KPI cards, charts, and tables update to reflect the selected range
- Date range label in the header updates accordingly

---

### US-06 — Export analytics report
**As a** court owner,  
**I want to** export the dashboard analytics data,  
**so that** I can share it with partners or use it in external tools.

**Acceptance Criteria:**
- "Xuất báo cáo" button in the dashboard header
- Export includes: KPI summary, per-hour chart data, per-day breakdown table
- Supported format: CSV (required), PDF (optional)

---

## Epic 3: Đặt Slot (Book Slot)
*EPIC-8 in build plan.*  
**Target: May 12–14**

### US-07 — Create a slot for myself as owner
**As a** court owner,  
**I want to** create a slot and assign it to myself,  
**so that** I can reserve court time for personal use or internal events without going through the customer booking flow.

**Acceptance Criteria:**
- Owner can select court, date, start/end time and mark it as an "Owner slot"
- Owner slot appears in the calendar as a distinct state (e.g. different color from customer bookings)
- Owner slot blocks the time from customer booking
- No payment required for owner slots

---

### US-08 — Create a manual booking for a walk-in customer · SPB-071 · `M` · `1d`
**As a** court owner,  
**I want to** manually add a booking for a customer at the counter,  
**so that** walk-in slots are recorded in the system.

**Acceptance Criteria:**
- Form fields: court selection, sport type (auto-filled), date, start time, end time, customer name, phone, notes
- Time inputs bounded to operating hours (06:00–22:00)
- Duration auto-calculates from start/end time
- Required fields: court, date, start time, end time; phone optional but validated if provided
- Validation: overlapping slots for the same court are not allowed

---

### US-09 — View live price summary before confirming a booking
**As a** court owner,  
**I want to** see a real-time pricing breakdown as I fill the booking form,  
**so that** I can communicate the total cost to the customer before confirming.

**Acceptance Criteria:**
- Sticky sidebar shows: court fee (duration × price/hour), additional fees, total
- Summary updates immediately when time or price inputs change
- Warning displayed: "Default payment method: Pay at court"

---

### US-10 — Override price or duration for a booking
**As a** court owner,  
**I want to** edit the price per hour or duration inline on the booking form,  
**so that** I can apply discounts or fix data-entry errors.

**Acceptance Criteria:**
- Price/hour and duration fields are directly editable in the form
- Total recalculates automatically after any edit
- Overridden price is visually distinguished from the default (e.g. different border color)
- Override is saved as part of the booking record

---

### US-11 — Confirm or cancel a booking in progress
**As a** court owner,  
**I want to** confirm or discard a booking I'm composing,  
**so that** I don't accidentally create incorrect entries.

**Acceptance Criteria:**
- "Xác nhận đặt sân" submits and navigates to the booking detail or today's list
- "Hủy" discards the form (with a confirmation dialog if any field has been filled)
- On success, the new booking appears in the request list with status "Confirmed"

---

### US-12 — View weekly court schedule · SPB-070 · `M` · `1d`
**As a** court owner,  
**I want to** see a 7-day calendar grid for each court,  
**so that** I have a visual overview of all booked, available, and blocked slots.

**Acceptance Criteria:**
- Horizontal chips switch between courts (Sân 1, Sân 2, Pickleball A, etc.)
- Calendar: days as columns (Mon–Sun), hourly rows (06:00–22:00)
- Slot states rendered distinctly: Available (white), Booked (green), Blocked (gray), Maintenance (light gray + label)
- Today's column is highlighted
- Calendar scrollable vertically (hours) and horizontally (courts)
- Navigation arrows shift the view ±7 days; "Hôm nay" resets to current week

---

### US-12b — Block a time slot · SPB-072 · `M` · `0.5d`
**As a** court owner,  
**I want to** block a time slot from being booked,  
**so that** I can reserve time for maintenance, personal use, or other non-bookable activities.

**Acceptance Criteria:**
- Tap an open slot → "Khoá giờ" option appears with an optional reason field
- `slots.status = blocked`; slot is immediately removed from the player-facing slot picker
- Blocked slot shown in gray on the owner calendar with a lock icon and the reason (if provided)
- Cannot block a slot with `status = booked`; action is disabled and shows an error
- Owner can unblock a blocked slot at any time; `slots.status` reverts to `open`

---

### US-13 — Set a recurring schedule for a court · SPB-073 · `S` · `1.5d`
**As a** court owner,  
**I want to** define a recurring availability schedule,  
**so that** I don't have to recreate slots manually each week.

**Acceptance Criteria:**
- "Đặt lịch cố định" opens a recurring-schedule editor
- Recurrence options: daily, weekdays only, weekends only, custom days
- Operating hours range configurable per rule
- Generates slots for the next 4 weeks from the selected start date
- Skips dates where slots already exist (no overwrite); shows conflict count before the owner confirms
- Manual overrides (blocked/maintenance slots) are preserved

---

## Epic 4: Các Yêu Cầu (Booking Requests)
*EPIC-7 in build plan. Core daily workflow.*  
**Target: May 8–11**

### US-14 — View all incoming booking requests · SPB-060 · `M` · `1d`
**As a** court owner,  
**I want to** see a list of all booking requests with their statuses,  
**so that** I can manage my daily queue efficiently.

**Acceptance Criteria:**
- List grouped by slot time; each card shows: customer name, booking ID, time slot, court, status badge
- Status badges: yellow = Pending (Chờ xác nhận), green = Confirmed (Đã xác nhận), gray = Cancelled (Đã huỷ)
- Summary bar shows: total bookings count, pending count, expected revenue for the day
- Cancelled bookings de-emphasized (reduced opacity, greyed avatar)
- Date picker to navigate to other days (default: today)
- Paginated (e.g. 4 per page) with record count "Hiển thị X trong Y đơn"; default sort: ascending by start time
- List scoped to `courts.owner_id = auth.uid()` via RLS

---

### US-15 — Approve a booking request · SPB-061 · `M` · `0.5d`
**As a** court owner,  
**I want to** approve a pending booking request,  
**so that** the customer receives timely confirmation of their slot.

**Acceptance Criteria:**
- Pending cards show "Duyệt" (Approve) button; confirmation in ≤ 2 taps
- `bookings.status → confirmed`
- Customer's phone number is revealed on the card only after approval (hidden before)
- Player receives in-app notification: "Đặt sân thành công"
- Card badge updates to Confirmed; action buttons disappear
- Action undoable within a short grace period via "Hoàn tác" snackbar

---

### US-16 — Reject a booking request · SPB-062 · `M` · `0.5d`
**As a** court owner,  
**I want to** reject a pending booking request,  
**so that** I can free the slot for other customers.

**Acceptance Criteria:**
- Pending cards show "Từ chối" (Reject) button; tapping opens an optional reason field then a confirm step
- `bookings.status → cancelled`; `slots.status → open` (slot is freed)
- Player receives an in-app notification with the reason if one was provided
- Card transitions to cancelled style (greyed-out)
- Action undoable within a short grace period via "Hoàn tác" snackbar

---

### US-17 — Filter booking requests
**As a** court owner,  
**I want to** filter the request list by status or court,  
**so that** I can focus on a specific subset (e.g. all pending).

**Acceptance Criteria:**
- "Bộ lọc" button opens filter panel
- Filter options: status (all / pending / confirmed / cancelled), court name
- Applied filters shown as chips above the list
- List updates immediately on apply

---

### US-18 — Export booking requests report
**As a** court owner,  
**I want to** export the booking list,  
**so that** I can share or archive records.

**Acceptance Criteria:**
- "Xuất báo cáo" button triggers download or share
- Export includes: booking ID, customer name, phone, time slot, court, status, amount
- Supported format: CSV (required), PDF (optional)

---

## Epic 5: Chi Tiết Slot (Slot Details)

### US-19 — View the player list for a slot
**As a** court owner,  
**I want to** see the list of players registered in a specific slot,  
**so that** I can verify attendance and prepare the court accordingly.

**Acceptance Criteria:**
- Slot detail screen lists all registered players: name, avatar, booking status
- Shows current player count vs. court capacity (e.g. "3/4 players")
- Players who have paid are visually distinguished from those who haven't

---

### US-20 — Add a player to a slot
**As a** court owner,  
**I want to** manually add a player to an existing slot,  
**so that** walk-ins or phone bookings are reflected in the player list.

**Acceptance Criteria:**
- "Thêm người chơi" button opens a player search or manual-entry form
- Search by name or phone number against existing player records
- If no record found, option to create a new player inline (name + phone)
- Added player appears immediately in the slot's player list
- Adding beyond capacity shows a warning but does not hard-block (owner override)

---

### US-21 — View payment status of a slot
**As a** court owner,  
**I want to** see which players in a slot have paid and which haven't,  
**so that** I can collect outstanding payments before or after the session.

**Acceptance Criteria:**
- Payment status per player: Paid (green), Unpaid (yellow), Partial (orange)
- Total collected vs. total expected shown as a summary
- Owner can mark a player as paid directly from this screen
- Payment method recorded: Cash, Transfer, App wallet

---

### US-22 — View the schedule of a slot
**As a** court owner,  
**I want to** see the date, time, court, and duration details of a specific slot,  
**so that** I have the full context when managing it.

**Acceptance Criteria:**
- Slot detail header shows: court name, sport type, date, start–end time, duration
- Displays any notes attached to the slot
- Links back to the weekly calendar view at the relevant time

---

## Epic 6: Danh Sách Người Chơi (Player List)

### US-23 — View all players who have visited the facility
**As a** court owner,  
**I want to** see a list of all players who have ever booked or played at my facility,  
**so that** I can understand my customer base, reward loyal players, and re-engage lapsed ones.

**Acceptance Criteria:**
- Player list shows: avatar, name, phone, sport(s) played, skill level, total visits, last visit date
- Default sort: most recent visit first
- Search by name or phone number
- Filter by sport type or visit frequency (e.g. "visited in last 30 days")
- Tapping a player navigates to their detail screen

---

## Epic 7: Chi Tiết Người Chơi (Player Details)

### US-24 — View a player's profile and booking history
**As a** court owner,  
**I want to** see a player's full profile including visit history and sport preferences,  
**so that** I have context when they show up or call to book.

**Acceptance Criteria:**
- Profile shows: name, phone, avatar, member since date
- Booking history: list of past and upcoming slots (date, court, sport, payment status)
- Aggregate stats: total visits, total spend, favourite sport, favourite time slot
- Tapping a past slot navigates to that slot's detail screen (US-19)

---

### US-25 — Evaluate a player's skill level by sport
**As a** court owner,  
**I want to** assign a skill level rating to a player for each sport they play,  
**so that** I and other players can make informed matchmaking decisions.

**Acceptance Criteria:**
- Skill level field per sport: Beginner / Intermediate / Advanced / Professional (or numeric scale)
- Owner can set or update the rating from the player detail screen
- Rating is visible on the player's profile and in the player list
- Rating history is logged (who rated, when) for transparency
- Players cannot edit their own owner-assigned rating

---

## Epic 8: Navigation & Global Shell
*EPIC-10 in build plan.*  
**Target: May 15–16**

### US-26 — Navigate between main sections via the sidebar
**As a** court owner,  
**I want to** navigate between Home, Schedule, Analytics, and Notifications from a persistent sidebar,  
**so that** I can switch contexts quickly.

**Acceptance Criteria:**
- Sidebar always visible on desktop (≥1024px); collapses to drawer on mobile
- Active section highlighted with a distinct indicator (green border + background)
- Nav items: Home, Schedule, Analytics, Notifications, Support, Logout

---

### US-27 — Search bookings from the top bar
**As a** court owner,  
**I want to** search for a booking by customer name or booking ID,  
**so that** I can look up specific records instantly.

**Acceptance Criteria:**
- Search input always visible in the top app bar
- Results shown as a dropdown or navigate to a filtered list
- Matches on: customer name, booking ID (e.g. SPB-060), phone number

---

### US-28 — Notification centre · SPB-063 + SPB-091 · `M` · `1d`
**As a** court owner,  
**I want to** be alerted in real time when new bookings arrive or are cancelled,  
**so that** I can respond quickly without manually refreshing.

**Acceptance Criteria:**
- Bell icon in the top bar shows an unread count badge
- Badge updates in real time via Supabase Realtime subscription on the `notifications` table
- Notification centre lists all alerts with: message, timestamp; default sort newest first
- Tapping a notification navigates directly to the relevant booking
- Badge clears (and notifications marked read) when the centre is opened; "Mark all as read" also available
- Tapping the bell icon from the requests screen navigates to the pending list

---

### US-29 — Quick-add a new booking via FAB
**As a** court owner,  
**I want to** tap a floating action button to start a new booking from any screen,  
**so that** I can handle walk-ins without navigating through menus.

**Acceptance Criteria:**
- FAB (+) fixed to bottom-right on the Home/requests screen
- Tapping navigates to the manual booking form (US-08)
- FAB hidden on screens where booking creation is already the primary action

---

## Build Schedule

| Epic | Stories | Est. days | Window |
|---|---|---|---|
| EPIC-0: Auth + i18n (owner) | US-00, US-00b | 1 | May 4 |
| EPIC-1: Setup | US-01 | — | May 4–5 |
| EPIC-7: Booking Requests | US-14–18 | 2.5 | May 8–11 |
| EPIC-8: Đặt Slot / Schedule | US-07–13 | 3.5 | May 12–14 |
| EPIC-9: Dashboard / Analytics | US-02–06 | 1.5 | May 14–15 |
| EPIC-10: Notifications + Shell | US-26–29 | 1 | May 15–16 |
| EPIC-5–7: Slot Details, Players | US-19–25 | — | Post-launch |
| **Total (launch scope)** | **~16** | **~9.5** | **~May 17** |

**Critical path:** Auth → Booking Requests → Schedule Management  
**Runs parallel with customer app from May 5**  
**Post-launch:** Epics 5–7 (Slot Details, Player List, Player Details)

---

*Last updated: 2026-05-03*

# Owner (Court Manager) User Flow

**App:** Owner Dashboard (Flutter Web)
**Auth:** Email + password
**Payment collected:** Cash at venue by owner (no platform involvement)

---

## Entry Points

| Source | Entry path |
|---|---|
| SpB salesperson in-person visit (primary) | Demo on phone → owner fills `/cho-chu-san` lead form |
| SpB flyer / name card | QR on card → `/cho-chu-san` |
| Facebook group post | Link → `/cho-chu-san` |
| SpB team sends login link | Direct email with credentials |

---

## Onboarding Flow (one-time, assisted by SpB team)

```
[1] Owner fills lead form
    - Name, phone, court name, district
    - Written to `leads` table
        │
        ▼
[2] SpB team contacts owner within 24h
    - Phone call to confirm interest
    - Schedule in-person visit
        │
        ▼
[3] In-person visit by SpB team
    - Show live demo (fake booking pre-loaded)
    - Explain: free 3 months, no setup fee, we bring customers
        │
        ▼
[4] SpB team creates court profile (v1: manual data entry)
    - Upload court photos
    - Set: name, address, lat/lng, sports[], amenities[], price/hr
    - courts.status = approved
        │
        ▼
[5] SpB team creates owner account
    - Email + temp password via Supabase Auth
    - users.role = owner
    - courts.owner_id = owner.id
        │
        ▼
[6] SpB team (together with owner) creates first week's slots
    - Set recurring weekly schedule (Mon–Sun, hours open)
    - Or create slots manually for next 7 days
        │
        ▼
[7] Owner receives credentials + Zalo support number
    - SpB stays on Zalo for first 7 days to help with any issues
```

---

## Daily Workflow

```
[1] Receive booking notification
    - FCM push: "Yêu cầu đặt sân mới — 7pm hôm nay. Mở app để xác nhận."
    - In-app notification badge (if app already open) via Supabase Realtime
        │
        ▼
[2] Open Owner Dashboard
    - Login with email + password
    - If session alive → skip login
        │
        ▼
[3] Home: Today's Bookings
    - List grouped by time slot
    - Status badges: Chờ xác nhận / Đã xác nhận / Đã huỷ
    - Date picker to navigate to other days
        │
        ▼
[4] Tap pending booking → Booking Detail
    Shows: player name, time slot, notes (if any)
        │
        ▼
[5] Decision: Approve or Reject
    │
    ├── APPROVE
    │     Tap "Duyệt"
    │     bookings.status = confirmed
    │     Player phone number revealed
    │     Option: call player to verbally confirm
    │     Player receives in-app notification: "Đặt sân thành công"
    │
    └── REJECT
          Tap "Từ chối"
          Optional: enter reason (e.g. "Sân đang bảo trì")
          bookings.status = cancelled
          slots.status    = open
          Player receives notification with reason
        │
        ▼
[6] Player shows up (offline)
    - Owner confirms attendance (optional: mark as completed in v2)
    - Player pays cash at venue
    - Transaction complete — platform not involved
```

---

## Schedule Management

```
[Schedule tab]
        │
        ▼
[1] Calendar view
    - 7-day grid with hourly rows
    - Colors: open (white) / booked (green-100 fill, green-500 border) / blocked (grey) / maintenance (light grey + label)
    - Navigate forward / back by week
        │
        ├── [2] Create slot
        │     Tap empty cell → form: date, start, end, price override (optional)
        │     Validation: no overlapping slots
        │     → Slot appears as open (white)
        │
        ├── [3] Block slot
        │     Tap open slot → "Khoá giờ" + optional reason
        │     Cannot block slots with status = booked
        │     → Slot turns grey; not visible to players
        │
        └── [4] Set recurring schedule
              "Đặt lịch cố định"
              Choose: days of week + open hours
              Generates slots for next 4 weeks
              Skips existing slots (no overwrite)
              Shows conflict count before confirming
```

---

## Weekly Analytics

```
[Analytics tab]
        │
        ▼
[1] Weekly summary cards
    - Total bookings this week
    - Confirmed bookings
    - Estimated revenue (bookings × price/hr)
    - Week-over-week delta (↑ / ↓)
        │
        ▼
[2] Slot utilisation by hour
    - Bar chart: bookings per hour across the week
    - Highlights top 3 busiest slots
    - Insight: "7pm–9pm là giờ cao điểm của bạn"
```

---

## Notification Centre

```
[Bell icon — top right of dashboard]
    - Badge shows unread count
    - Realtime update via Supabase subscription
        │
        ▼
[Notification list]
    - New booking request:  "Nguyễn Văn A muốn đặt 7pm hôm nay"
    - Player cancelled:     "Booking 7pm hôm nay đã bị huỷ"
    - Tap any notification → navigates to that booking
    - "Mark all read" clears badge
```

---

## Edge Cases

| Situation | Behaviour |
|---|---|
| Player cancels before owner responds | Booking shows as Đã huỷ; slot re-opens automatically |
| Owner tries to block a confirmed booking | Error: "Không thể khoá giờ đã có booking. Huỷ booking trước." |
| Owner approves a booking player already cancelled | System shows cancelled state; approval has no effect |
| Owner hasn't responded in 2h | v1: nothing (owner responsible); v2: auto-remind via FCM push |
| Owner creates overlapping slots | Validation error: "Giờ này đã có slot. Chọn giờ khác." |
| Owner forgets password | "Quên mật khẩu" → Resend sends reset email |
| Recurring schedule conflicts with existing slots | Show count: "3 slot bị trùng sẽ bị bỏ qua" — existing slots kept |
| Court has no active slots | Dashboard shows "Chưa có slot nào. Tạo lịch sân?" prompt |

---

## Screens summary

| Screen | Route / Widget | Story ref |
|---|---|---|
| Login | `/login` | SPB-013 |
| Today's Bookings (Home) | `/` | SPB-060 |
| Booking Detail | `/bookings/:id` | SPB-061, SPB-062 |
| Notifications | `/notifications` | SPB-063, SPB-091 |
| Calendar / Schedule | `/schedule` | SPB-070 |
| Create Slot | `/schedule/new` | SPB-071 |
| Block Slot | `/schedule/:slotId/block` | SPB-072 |
| Recurring Schedule | `/schedule/recurring` | SPB-073 |
| Weekly Analytics | `/analytics` | SPB-080, SPB-081 |

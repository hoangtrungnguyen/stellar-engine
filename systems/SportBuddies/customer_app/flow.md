# Customer (Player) User Flow

**App:** Customer App (Flutter Web)
**Auth:** Email + password (with email verification) or Google OAuth (Gmail)
**Payment:** Cash at venue (no online payment in v1)

---

## Entry Points

| Source | Entry path |
|---|---|
| Landing page CTA | `sportbuddies.vn` → "Đặt sân ngay" |
| TikTok / Facebook Ad | Direct link to app URL |
| QR code at court venue | `/san/[slug]` → redirect to app, court pre-selected |
| Friend referral link | `/invite/[code]` → app opens with free booking credit |
| Direct URL (returning user) | App URL → skip auth if session alive |

---

## Happy Path

```
[1] Open Customer App
        │
        ▼
[2] Auth check
    ├── Logged in → go to [4]
    └── Not logged in → [3]
        │
        ▼
[3] Login / Sign-up screen
    ├── Email + password (sign up)
    │     Enter email + password → Supabase signUp →
    │     Verification email sent via Resend →
    │     User clicks link in email → email confirmed →
    │     Redirected to app, auto-logged-in
    │
    ├── Email + password (login)
    │     Enter email + password → signInWithPassword → logged in
    │     "Quên mật khẩu?" → password reset email
    │
    └── Google OAuth (Gmail)
          "Tiếp tục với Google" → Supabase OAuth → logged in
          (email auto-verified via Google)
        │
        ▼
[4] Map screen (Home)
    - Request GPS permission
      ├── Granted → map centers on user location
      └── Denied  → map centers on HCMC default (10.776°N, 106.701°E)
    - Load courts where `status = approved` from Supabase
    - Show pins: green (open slots) / red (fully booked)
        │
        ▼ (optional)
[5] Filter
    ├── Sport type: Tất cả / Bóng đá / Cầu lông / Pickleball / Tennis / Đa năng
    └── Distance: 1km / 3km / 5km
        │
        ▼
[6] Tap court pin → Court Detail screen
    Shows: photo carousel, name, address, sports, price/hr,
           amenities, description
    CTA: "Đặt sân ngay"
        │
        ▼
[7] Slot Picker
    - Tabs: Today + next 6 days
    - Each slot: start time, end time, price
    - Greyed out: booked or blocked slots
    - Select an open slot
        │
        ▼
[8] Booking Confirmation screen
    - Summary: court name, date, time, price
    - "Thanh toán tại sân" notice (prominent)
    - Name + phone pre-filled from profile (editable)
    - Tap "Xác nhận đặt sân"
        │
        ▼
[9] Atomic booking (create_booking() RPC)
    ├── Slot taken (race condition)
    │     → Error toast: "Slot vừa được đặt, chọn giờ khác"
    │     → Return to [7]
    └── Success
          bookings.status = pending
          slots.status    = booked
          Notification inserted for owner
        │
        ▼
[10] Booking Success screen
    - Booking ID, court, date/time, price
    - "Chờ chủ sân xác nhận" badge
    - "Nhớ mang tiền mặt" reminder
    - CTAs: "Xem lịch đặt" | "Về bản đồ"
        │
        ▼
[11] Owner response (async)
    ├── APPROVED
    │     In-app notification: "Đặt sân thành công! Đến đúng giờ nhé 🟢"
    │     bookings.status = confirmed
    │     → Player shows up, pays cash at venue
    │     → (manual / future) bookings.status = completed
    │
    └── REJECTED
          In-app notification: "Chủ sân không thể nhận booking này"
          + rejection reason (if provided)
          bookings.status = cancelled
          slots.status    = open
          → Player returns to [7] to pick another slot
```

---

## My Bookings

```
[Profile / Bookings tab]
    │
    ├── Upcoming tab
    │     Lists: pending + confirmed bookings (sorted by start_at ASC)
    │     Status badges: Chờ xác nhận (yellow) / Đã xác nhận (green)
    │     Action: Cancel (pending only)
    │               → bookings.status = cancelled
    │               → slots.status = open
    │               → Owner notified
    │
    └── History tab
          Lists: completed + cancelled bookings (sorted by start_at DESC)
          Action: "Đặt lại" → navigates to Court Detail [6] for that court
```

---

## Edge Cases

| Situation | Behaviour |
|---|---|
| GPS permission denied | Map shows HCMC center; user can pan/zoom manually |
| No courts in filter range | Empty state: "Không có sân trong khu vực này. Mở rộng phạm vi?" |
| All slots greyed out | Court detail shows "Hết slot hôm nay" with next available date |
| Slot taken between [7] and [9] | Error toast at [9]; return to slot picker with fresh data |
| No internet connection | Cached map tiles shown; booking attempt shows "Không có mạng" |
| Email not verified at login attempt | Show "Vui lòng kiểm tra email để xác minh" + "Gửi lại email" button (max 1/min) |
| Password reset email | Resend email → user clicks link → enter new password → auto-login |
| User signs up with Gmail then later tries email/password | Accounts merged on email match — show "Tài khoản này đã đăng ký bằng Google. Đăng nhập với Google?" |
| User cancels a confirmed booking | Cancel not allowed — only pending bookings can be cancelled |
| Duplicate booking same slot | `create_booking()` RPC prevents this at DB level (row lock) |

---

## Screens summary

| Screen | Route / Widget | Story ref |
|---|---|---|
| Login / Sign-up | `/login`, `/signup` | SPB-010, SPB-011 |
| Email verification callback | `/auth/callback` | SPB-010 |
| Profile | `/profile` | SPB-012 |
| Map (Home) | `/` | SPB-030, SPB-031 |
| Court Detail | `/court/:id` | SPB-040 |
| Slot Picker | `/court/:id/book` | SPB-041 |
| Booking Confirmation | `/court/:id/book/confirm` | SPB-042, SPB-043 |
| Booking Success | `/booking/:id/success` | SPB-044 |
| My Bookings — Upcoming | `/bookings` | SPB-050 |
| My Bookings — History | `/bookings/history` | SPB-051 |
| Notifications | `/notifications` | SPB-090 |

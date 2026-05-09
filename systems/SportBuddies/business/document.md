# SportBuddies — Original Vision (Historical)

> **⚠️ This document is the original product vision (pre-PRD).**
> **For the authoritative product scope, see [`PRD_business.md`](./PRD_business.md).**
>
> Some ideas described below were considered during early ideation but are **out of scope** for the v1 launch (June 1, 2026): partner matching, in-app chat, court ratings/reviews, native apps. These are deferred to v2 based on post-launch user feedback.

---

## Genesis

**Project name:** SportBuddies (SpB)

**Tagline:** *Connecting sports hosts with sports buddies*

**Why this project:** A platform to connect owners of sports fields and organisers of sporting events with people looking for fields to play on, and (longer-term) with companions to play alongside.

**Target users:** People looking for a place to play their favourite sport in HCMC, plus the field owners and operators who want to fill idle time slots and grow beyond word-of-mouth.

---

## Original market problems identified

Vietnamese sports-booking platforms in 2025–2026 share these gaps:

- Chủ sân chưa nắm rõ lịch trên app
- Đặt qua app quá rườm rà
- Chưa có nhiều sân cập nhật app/giá
- Mất nhiều thời gian để đặt sân
- Chưa thể tìm được sân vãng lai
- Không có khuyến mãi
- Không được quảng bá rộng rãi
- Không có ai kiểm định sân
- Chưa có nhiều bộ môn mới (gym / pickleball / 3 môn phối hợp)

The PRD addresses the first eight directly. Bộ môn mới is addressed by supporting Pickleball and Đa năng (multi-purpose) courts at launch.

---

## Original design philosophy

Carried into v1 unchanged:
- **Dễ nhìn – trực quan – ít thao tác** (clean, intuitive, minimal taps)
- **Map-first**: location and time are primary axes
- **Mobile-first** (web PWA for v1)
- **Booking < 60s** from app open to confirmed slot

---

## Future vision (v2+, post-launch)

Ideas explored in early scoping but **explicitly out of scope for v1**:

| Idea | Status |
|---|---|
| Partner matching (find someone to play with) | v2 — partial coverage via play-together access policy on confirmed slots |
| In-app chat between players | v2 |
| Court ratings & reviews | v2 |
| Group bookings | v2 |
| Tournament organisation | v2+ |
| Loyalty / points programme | v2+ |
| AI-suggested courts | v2+ |
| Native iOS/Android apps | v2 (same Flutter codebase) |

See [`PRD_business.md` — "What We Are NOT Building (v1)"](./PRD_business.md) for the canonical out-of-scope list.

---

*This file is preserved for historical context only. All product decisions reference `PRD_business.md`.*

# SportBuddies — Component Specs

## Marketing site components

### Hero (MKT-001)
- Background: `neutral-50` with subtle diagonal sports-field line texture (SVG, `opacity: 0.04`)
- Headline: `display-xl` (desktop) / `display-lg` (mobile), Sora 800, `neutral-900`
- Subheadline: `body-lg`, Plus Jakarta Sans 400, `neutral-600`, max-width 480px
- Primary CTA button: `primary` bg, white text, `radius-full`, height 52px, padding `0 32px`, `labelLarge`
- Secondary CTA: ghost, `neutral-700`, underline on hover
- Phone mockup: right-aligned on desktop, centered below text on mobile, drop shadow `shadow-lg`, `radius-xl` frame
- Above the fold on iPhone SE (375px): headline + CTA must be visible without scrolling

### Stats bar (MKT-003)
- Background: `primary` green `#16A34A`
- Text: white, `heading-3` Sora 700
- Numbers: `tabular-nums`, animate count-up on scroll-enter (`motion-counter`)
- Separator: thin white vertical line, `opacity: 0.3`
- Layout: flex row, centered, `space-16` gap between stats

### Sport card (MKT-004)
- Size: equal-width 3-column grid (desktop), horizontal scroll on mobile
- Background: `surface`, `radius-lg`, `shadow-md`
- Sport icon: 48×48px colored icon on `primary-light` circle bg
- Title: `heading-3`, `neutral-900`
- Description: `body-sm`, `neutral-600`
- Pickleball badge: "Môn mới" pill, `primary` bg, white text, `radius-full`, `label` size
- No individual CTA per card — single "Mở app ngay" CTA below the grid

### App screenshot carousel (MKT-005)
- Phone frame: `neutral-900` frame, `radius-xl`, 8px frame width
- Captions below each: `body-sm`, `neutral-600`, centered
- Mobile: snap scroll, 1 card visible + 20% peek of next
- Desktop: 3 frames side-by-side, center card slightly larger (scale 1.05)

### Lead form — Owner page (MKT-010)
- Input height: 48px, `radius-md`, border `neutral-200`, focus border `primary`
- Label: `label`, `neutral-700`, `space-2` gap above input
- Error: `danger` text below input, `body-sm`
- Submit button: full-width on mobile, `primary`, 52px height
- District dropdown: 24 HCMC districts

### Agent registration form (MKT-021)
- Same input spec as owner form above
- Role dropdown: Huấn luyện viên / Trưởng nhóm thể thao / Chủ gym / Cửa hàng dụng cụ / Khác
- network_description: textarea, 3 rows, resize-none
- Success state: green checkmark icon + success message, form hidden

---

## Customer app components (Flutter)

### Map pin (SPB-031)
- Shape: teardrop (32×40px), colored fill, white outline 1.5px
- Icon inside: 16×16px sport icon (football/badminton/pickleball) or generic court icon
- Green fill (`#22C55E`) → available; Red fill (`#EF4444`) → full; Orange fill (`#F97316`) → selected
- Tap: pin scales 1.0→1.2 with `motion-spring` bounce
- Cluster (≥5 pins nearby): grey circle with count number

### Filter chip (SPB-032)
- Height: 36px, `radius-full`, `space-3` horizontal padding
- Default: `surface` bg, `neutral-200` border, `neutral-700` text
- Active: `primary-light` bg, `primary` border, `primary` text, Sora 600
- Row: horizontal scroll, no wrap, `space-2` gap

### Court detail (SPB-040)
- Photo carousel: full-width, 220px height, dots indicator below
- "Đặt sân ngay" sticky CTA at bottom: full-width, 52px, `primary`, always visible above safe area
- Info rows: icon + label + value, `space-4` vertical gap

### Slot picker (SPB-041)
- Date tabs: horizontal scroll, today highlighted with `primary` underline
- Slot pill: 120×48px, `radius-md`
  - Open: `success-bg` bg, `success` border, `neutral-900` text
  - Booked: `neutral-100` bg, `neutral-200` border, `neutral-300` text (disabled)
  - Selected: `primary` bg, white text
- Grid: 2-column on narrow screens, 3-column on wide

### Booking confirmation (SPB-042)
- "Thanh toán tại sân" notice: `warning-bg` banner, `warning` left border 4px, `body-sm`
- Submit button: full-width, 52px, `primary`, loading spinner replaces label during RPC

### Status badge
- Height: 24px, `radius-sm`, `space-3` horizontal padding, `label` size
- Colors: per semantic usage table in `colors.md`

### Bottom navigation
- Height: 64px + safe area inset
- 3 tabs: Map / My Bookings / Profile
- Active icon: `primary`, label `label-small` `primary`
- Inactive: `neutral-600`

### Empty state
- Centered illustration (SVG, 120×120px) + heading `titleMedium` + body `bodyMedium` + optional CTA
- Used on: empty bookings list, map with no courts in radius

---

## Owner dashboard components (Flutter)

### Booking card (SPB-060)
- Background: `surface`, `radius-md`, `shadow-sm`, `space-4` padding
- Left border: 4px colored by status (warning/success/neutral-200)
- Player name: `titleSmall`; time: `bodyMedium` `neutral-600`
- Action buttons: "Duyệt" (`success` outlined) + "Từ chối" (`danger` outlined), right-aligned
- After approval: player phone number revealed with phone icon

### 7-day calendar grid (SPB-070)
- Column header: day name + date, today column `primary-light` tinted
- Row header: hourly labels (06:00–22:00), `caption` size, `neutral-600`
- Cell: 48px height minimum, colored by slot state (see `colors.md`)
- Tap empty cell: bottom sheet slides up with create-slot form
- Horizontal scroll on narrow screens (min column width 56px)

### Analytics card (SPB-080)
- `radius-lg`, `shadow-md`, `space-6` padding
- Metric number: `display-lg` Sora 700
- Delta: `▲ +12%` green / `▼ -5%` red, `labelMedium`
- Label below: `bodySmall` `neutral-600`

### Bar chart (SPB-081)
- `primary` bars with `primary-light` at 30% opacity for empty columns
- Top 3 busiest: solid `primary`; rest: `primary` at 50% opacity
- X-axis: hour labels, `caption`, `neutral-600`
- No chart library required for v1 — render as a row of proportional `Container` widgets

---

## OG image spec (MKT-050)
- Size: 1200×630px
- Background: `neutral-900` with subtle grid overlay
- Left half: headline text in Sora 800, white, large
- Right half: phone mockup showing map screen
- Bottom strip: `primary` orange band with "sportbuddies.vn"
- Variations needed: homepage / `/cho-chu-san` / `/dai-ly` / `/pickleball`

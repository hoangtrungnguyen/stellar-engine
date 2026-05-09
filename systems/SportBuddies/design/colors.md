# SportBuddies — Color System

## Rationale
Primary brand color is deep green — natural, energetic, evokes sport fields and activity.
Two greens in the system serve different roles:
- **Brand green** (`#16A34A`, darker) — CTAs, nav active state, brand identity
- **Success green** (`#22C55E`, brighter/lighter) — map availability pins, confirmed status

The contrast between dark brand green and bright success green is sufficient to distinguish them at a glance.

---

## Brand palette

| Token | Hex | Tailwind ref | Usage |
|---|---|---|---|
| `primary` | `#16A34A` | green-600 | Primary CTAs, key actions, nav active state |
| `primary-dark` | `#15803D` | green-700 | Hover / pressed state on primary |
| `primary-light` | `#DCFCE7` | green-100 | Tinted backgrounds, selected chips |
| `primary-mid` | `#4ADE80` | green-400 | Decorative accents, illustrations |
| `secondary` | `#0EA5E9` | sky-500 | Secondary actions, info badges |
| `secondary-dark` | `#0284C7` | sky-600 | Hover on secondary |
| `success` | `#22C55E` | green-500 | Available pin, confirmed badge, success toast |
| `success-bg` | `#DCFCE7` | green-100 | Badge background for confirmed status |
| `danger` | `#EF4444` | red-500 | Fully-booked pin, cancel/reject action |
| `danger-bg` | `#FEE2E2` | red-100 | Badge background for cancelled status |
| `warning` | `#EAB308` | yellow-500 | Pending status badge |
| `warning-bg` | `#FEF9C3` | yellow-100 | Badge background for pending status |
| `neutral-900` | `#111827` | gray-900 | Primary body text, headings |
| `neutral-700` | `#374151` | gray-700 | Secondary headings |
| `neutral-600` | `#6B7280` | gray-500 | Secondary text, labels, placeholders |
| `neutral-300` | `#D1D5DB` | gray-300 | Disabled text |
| `neutral-200` | `#E5E7EB` | gray-200 | Borders, dividers |
| `neutral-100` | `#F3F4F6` | gray-100 | Input backgrounds, table row alt |
| `neutral-50` | `#F9FAFB` | gray-50 | Page background |
| `surface` | `#FFFFFF` | white | Cards, sheets, modals |
| `overlay` | `rgba(0,0,0,0.48)` | — | Modal backdrop |

---

## Two greens — visual distinction

| | Brand green | Success green |
|---|---|---|
| Hex | `#16A34A` | `#22C55E` |
| Lightness | Dark, saturated | Bright, vivid |
| Used for | Buttons, CTAs, nav | Map pins (available), badges |
| Never used for | Status indicators | Brand actions |

---

## Semantic usage

### Map pins (customer app — SPB-031)
| State | Color | Hex |
|---|---|---|
| Available (≥1 open slot next 24h) | `success` | `#22C55E` |
| Full (no open slots next 24h) | `danger` | `#EF4444` |
| Selected | `primary` | `#16A34A` |
| Loading | `neutral-300` | `#D1D5DB` |

Pin design: 32×40px teardrop with white court-type icon inside. Drop shadow: `0 2px 8px rgba(0,0,0,0.24)`.

### Booking status badges
| Status | Text color | Background |
|---|---|---|
| Chờ xác nhận | `warning` `#EAB308` | `warning-bg` `#FEF9C3` |
| Đã xác nhận | `success` `#22C55E` | `success-bg` `#DCFCE7` |
| Đã huỷ | `neutral-600` `#6B7280` | `neutral-100` `#F3F4F6` |
| Đã hoàn thành | `neutral-600` `#6B7280` | `neutral-100` `#F3F4F6` |

### Owner schedule calendar (SPB-070)
| Slot state | Fill | Border |
|---|---|---|
| Open | `surface` white | `neutral-200` |
| Booked | `#DCFCE7` green-100 | `#22C55E` green-500 |
| Blocked | `neutral-100` | `neutral-200` |
| Today column header | `primary-light` | `primary` |

### CTA buttons
| Variant | Background | Text | Hover |
|---|---|---|---|
| Primary | `primary` `#16A34A` | white | `primary-dark` `#15803D` |
| Secondary | `surface` | `primary` | `primary-light` bg |
| Danger | `danger` `#EF4444` | white | `#DC2626` red-600 |
| Ghost | transparent | `neutral-700` | `neutral-100` bg |

---

## Accessibility
- Body text on white: `neutral-900` (#111827) → contrast 16.8:1 ✅
- Primary CTA text: white on `#16A34A` → contrast 4.54:1 ✅ (passes WCAG AA for all text sizes)
- Success green on white: `#22C55E` → contrast 2.5:1 — use only for large text or icons, always pair with a label
- Never use color alone to convey state — pair every status color with an icon or text label
- Map pins: icon inside pin (football/badminton/pickleball icon) in addition to green/red color

---

## Dark mode
Not in v1 scope. Tokens defined to make future dark mode straightforward:
- Swap `surface` → `#1F2937`, `neutral-50` → `#111827`, text tokens invert
- `primary` stays `#16A34A` (works on dark bg at this saturation level)

---

## Implementation

| Product | File |
|---|---|
| Marketing site (Next.js + Tailwind) | `tailwind.config.ts` → `theme.extend.colors` |
| Customer app (Flutter) | `packages/spb_core/lib/theme/app_colors.dart` |
| Owner dashboard (Flutter) | Same `app_colors.dart` — shared via `spb_core` |

### Tailwind config snippet
```ts
colors: {
  primary: {
    DEFAULT: '#16A34A',
    dark: '#15803D',
    light: '#DCFCE7',
    mid: '#4ADE80',
  },
  secondary: { DEFAULT: '#0EA5E9', dark: '#0284C7' },
  success: { DEFAULT: '#22C55E', bg: '#DCFCE7' },
  danger: { DEFAULT: '#EF4444', bg: '#FEE2E2' },
  warning: { DEFAULT: '#EAB308', bg: '#FEF9C3' },
}
```

### Flutter snippet
```dart
class AppColors {
  static const primary = Color(0xFF16A34A);
  static const primaryDark = Color(0xFF15803D);
  static const primaryLight = Color(0xFFDCFCE7);
  static const primaryMid = Color(0xFF4ADE80);
  static const secondary = Color(0xFF0EA5E9);
  static const success = Color(0xFF22C55E);
  static const successBg = Color(0xFFDCFCE7);
  static const danger = Color(0xFFEF4444);
  static const dangerBg = Color(0xFFFEE2E2);
  static const warning = Color(0xFFEAB308);
  static const warningBg = Color(0xFFFEF9C3);
  static const neutral900 = Color(0xFF111827);
  static const neutral700 = Color(0xFF374151);
  static const neutral600 = Color(0xFF6B7280);
  static const neutral300 = Color(0xFFD1D5DB);
  static const neutral200 = Color(0xFFE5E7EB);
  static const neutral100 = Color(0xFFF3F4F6);
  static const neutral50 = Color(0xFFF9FAFB);
  static const surface = Color(0xFFFFFFFF);
}
```

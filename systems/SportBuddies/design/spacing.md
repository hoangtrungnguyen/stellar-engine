# SportBuddies — Spacing & Layout

## Base unit
**4px** — all spacing is a multiple of 4.

| Token | Value | Usage |
|---|---|---|
| `space-1` | 4px | Icon padding, micro gaps |
| `space-2` | 8px | Inline gaps, tight stacks |
| `space-3` | 12px | Badge padding, chip padding |
| `space-4` | 16px | Default inner padding, list item gaps |
| `space-5` | 20px | Card padding (mobile) |
| `space-6` | 24px | Section inner padding |
| `space-8` | 32px | Between cards, major gaps |
| `space-10` | 40px | Section vertical padding (mobile) |
| `space-12` | 48px | Section vertical padding (desktop) |
| `space-16` | 64px | Between major page sections |
| `space-20` | 80px | Hero vertical breathing room |
| `space-24` | 96px | Large section gap (desktop) |

---

## Border radius

| Token | Value | Usage |
|---|---|---|
| `radius-sm` | 6px | Badges, chips, small buttons |
| `radius-md` | 10px | Input fields, cards |
| `radius-lg` | 16px | Large cards, bottom sheets |
| `radius-xl` | 24px | Phone mockup frames, hero card |
| `radius-full` | 9999px | Pills, avatar, icon buttons |

---

## Elevation / shadows

| Level | CSS box-shadow | Usage |
|---|---|---|
| `shadow-sm` | `0 1px 3px rgba(0,0,0,0.08)` | Input hover, subtle card |
| `shadow-md` | `0 4px 12px rgba(0,0,0,0.10)` | Default card, dropdown |
| `shadow-lg` | `0 8px 24px rgba(0,0,0,0.12)` | Modal, bottom sheet |
| `shadow-pin` | `0 2px 8px rgba(0,0,0,0.24)` | Map pins |

---

## Grid — Marketing site

| Breakpoint | Columns | Gutter | Max content width |
|---|---|---|---|
| Mobile (`< 640px`) | 4 | 16px | 100% |
| Tablet (`640–1024px`) | 8 | 24px | 100% |
| Desktop (`> 1024px`) | 12 | 32px | 1200px |

Horizontal padding: `16px` mobile / `24px` tablet / `32px` desktop.

---

## Flutter layout constraints

| Context | Value |
|---|---|
| Screen horizontal padding | 16px |
| Bottom nav height | 64px |
| AppBar height | 56px |
| FAB bottom offset | 80px (above nav) |
| Bottom sheet border-radius | 20px top corners |
| Card elevation | 2 (Material) |
| Map pin size | 32×40px |
| Status badge height | 24px |
| Booking CTA button height | 52px |

---

## Motion

| Token | Duration | Easing | Usage |
|---|---|---|---|
| `motion-fast` | 120ms | ease-out | Hover states, badge updates |
| `motion-base` | 200ms | ease-in-out | Button press, color transitions |
| `motion-enter` | 280ms | cubic-bezier(0.16,1,0.3,1) | Modals, bottom sheets sliding in |
| `motion-exit` | 180ms | ease-in | Dismiss, slide out |
| `motion-spring` | 400ms | cubic-bezier(0.34,1.56,0.64,1) | Map pin bounce on select |
| `motion-counter` | 800ms | ease-out | Stats bar number count-up |

**Rules:**
- No motion on page load above the fold (don't delay the hero)
- Stats bar numbers animate count-up on first scroll into view
- Map pin bounces once when selected
- Bottom sheets slide up with `motion-enter`; never pop in instantly
- Respect `prefers-reduced-motion` — disable all non-essential animations

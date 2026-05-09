# SportBuddies — Typography System

## Rationale
Two fonts: a bold geometric display font for headings (energy, speed) + a clean humanist sans for body (readability at small sizes on mobile).
Vietnamese diacritics must render correctly — both fonts have full Vietnamese glyph coverage.

---

## Font stack

| Role | Font | Source | Fallback |
|---|---|---|---|
| Display / headings | **Sora** | Google Fonts | system-ui, sans-serif |
| Body / UI labels | **Plus Jakarta Sans** | Google Fonts | system-ui, sans-serif |

**Why Sora:** Wide geometric letterforms, strong at large sizes, excellent Vietnamese support. Feels sporty without being aggressive.
**Why Plus Jakarta Sans:** Friendly, highly legible at 14–16px, strong diacritic rendering for Vietnamese.

---

## Scale

### Marketing site (Next.js / rem)

| Token | Size | Line height | Weight | Font | Usage |
|---|---|---|---|---|---|
| `display-xl` | 56px / 3.5rem | 1.1 | 800 | Sora | Hero headline (desktop) |
| `display-lg` | 40px / 2.5rem | 1.15 | 800 | Sora | Hero headline (mobile) |
| `heading-1` | 32px / 2rem | 1.2 | 700 | Sora | Section headings |
| `heading-2` | 24px / 1.5rem | 1.3 | 700 | Sora | Sub-section headings |
| `heading-3` | 20px / 1.25rem | 1.3 | 600 | Sora | Card headings |
| `body-lg` | 18px / 1.125rem | 1.6 | 400 | Plus Jakarta Sans | Lead paragraphs |
| `body` | 16px / 1rem | 1.6 | 400 | Plus Jakarta Sans | Default body |
| `body-sm` | 14px / 0.875rem | 1.5 | 400 | Plus Jakarta Sans | Secondary text, captions |
| `label` | 13px / 0.8125rem | 1.4 | 600 | Plus Jakarta Sans | Form labels, badges |
| `caption` | 12px / 0.75rem | 1.4 | 400 | Plus Jakarta Sans | Timestamps, metadata |

### Flutter apps (sp units)

| Token | Size | Weight | Font | Usage |
|---|---|---|---|---|
| `titleLarge` | 22sp | 700 | Sora | Screen titles (AppBar) |
| `titleMedium` | 18sp | 600 | Sora | Card headings, section titles |
| `titleSmall` | 16sp | 600 | Plus Jakarta Sans | List item titles |
| `bodyLarge` | 16sp | 400 | Plus Jakarta Sans | Primary body text |
| `bodyMedium` | 14sp | 400 | Plus Jakarta Sans | Secondary body, descriptions |
| `bodySmall` | 12sp | 400 | Plus Jakarta Sans | Captions, metadata, timestamps |
| `labelLarge` | 14sp | 600 | Plus Jakarta Sans | Buttons, CTAs |
| `labelMedium` | 13sp | 600 | Plus Jakarta Sans | Status badges, chips |
| `labelSmall` | 11sp | 500 | Plus Jakarta Sans | Tab labels, nav labels |

---

## Key copy rules

- **Hero headline** (`display-xl`): max 4 words per line on mobile, tracking `-0.02em`
- **CTAs** (`label-large`): ALL CAPS not recommended for Vietnamese — use sentence case
- **Vietnamese diacritics**: ensure `font-feature-settings: "kern" 1` is on; test with "Đặt sân thể thao" at all sizes
- **Numbers in stats bar**: use `tabular-nums` (`font-variant-numeric: tabular-nums`) so live counters don't jitter

---

## Loading fonts

### Next.js (next/font)
```ts
import { Sora, Plus_Jakarta_Sans } from 'next/font/google'

export const sora = Sora({
  subsets: ['latin', 'vietnamese'],
  weight: ['400', '600', '700', '800'],
  variable: '--font-sora',
  display: 'swap',
})

export const plusJakarta = Plus_Jakarta_Sans({
  subsets: ['latin', 'vietnamese'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-plus-jakarta',
  display: 'swap',
})
```

### Flutter (pubspec.yaml)
```yaml
fonts:
  - family: Sora
    fonts:
      - asset: assets/fonts/Sora-Regular.ttf
      - asset: assets/fonts/Sora-SemiBold.ttf  weight: 600
      - asset: assets/fonts/Sora-Bold.ttf       weight: 700
      - asset: assets/fonts/Sora-ExtraBold.ttf  weight: 800
  - family: PlusJakartaSans
    fonts:
      - asset: assets/fonts/PlusJakartaSans-Regular.ttf
      - asset: assets/fonts/PlusJakartaSans-Medium.ttf   weight: 500
      - asset: assets/fonts/PlusJakartaSans-SemiBold.ttf weight: 600
      - asset: assets/fonts/PlusJakartaSans-Bold.ttf     weight: 700
```

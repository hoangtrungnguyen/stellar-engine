# SportBuddies — Marketing Website Epics & Stories

**Stack:** Next.js 15 (`output: "export"`) + Tailwind + Firebase Hosting `landing` target
**Live date:** May 2, 2026 (hard deadline — court outreach starts May 2)
**Three audiences:** Customers (players) · Owners (chủ sân) · Agents (đại lý / CTV)
**Sports covered:** Bóng đá (5vs5, 7vs7) · Cầu lông · Pickleball · Tennis · Đa năng
**Homepage primary goal:** Get players to open the Customer App
**Owner acquisition:** `/cho-chu-san` (dedicated page, linked from nav + homepage + footer)

---

## Page structure (homepage scroll order)

```
Nav          — logo | "Chủ sân?" → /cho-chu-san | "Đại lý?" → /dai-ly
Hero         — headline + "Mở app ngay" CTA + phone mockup (map with colored pins)
Stats bar    — live court + booking counts from Supabase
How it works — 4-step booking flow matching the actual app wizard
Sports       — Bóng đá / Cầu lông / Pickleball / Tennis / Đa năng
App preview  — phone screenshots: map, court detail, slot picker, booking confirmed
PWA install  — "Cài vào màn hình điện thoại"
Owner teaser — "Bạn là chủ sân?" → /cho-chu-san
Footer       — social + Zalo + owner link + sport page links
```

---

## EPIC-MKT-1: Core Landing Page (Player)
*Must be live May 2. Primary goal: get a player to tap "Mở app ngay".*
**Target: May 1–2**

### MKT-001 — Hero section `M | 0.5d`
As a player landing on the site, I want to understand the app in 5 seconds and open it immediately.
- Headline: "Đặt sân thể thao tại Sài Gòn trong 30 giây"
- Subheadline: "Xem sân trống gần bạn trên bản đồ — chọn giờ — xác nhận. Không cần gọi điện."
- Primary CTA: "Mở app ngay" → Customer App URL
- Secondary CTA: "Xem cách hoạt động" → smooth scroll to MKT-002
- Phone mockup showing the map screen with green (open) / yellow (few slots left) / red (full) pins
- Sport filter chips visible on mockup: Tất cả / Bóng đá / Cầu lông / Pickleball / Tennis
- Fully visible above the fold on iPhone SE (375px)

### MKT-002 — How it works `M | 0.5d`
As a player, I want to see the exact booking flow so I know how quick it really is.
- 4-step section matching the actual in-app booking wizard:
  1. Mở bản đồ → thấy sân xanh còn giờ trống gần bạn
  2. Chọn môn — lọc theo khoảng cách 1km / 3km / 5km
  3. Chọn khung giờ → xác nhận tên và số điện thoại
  4. Chờ chủ sân duyệt → nhận thông báo → đến sân trả tiền mặt
- Tagline: "Dưới 60 giây từ mở app đến đặt xong"

### MKT-003 — Stats bar `M | 0.5d`
As a new visitor, I want to see that real courts and players are already on SpB.
- Live counts from Supabase: `courts(status=approved)` and `bookings` total
- Display: "X sân đang hoạt động · Y lượt đặt sân"
- Falls back to hardcoded placeholder if Supabase call fails (no spinner visible)
- Positioned between hero and how-it-works

### MKT-004 — Sports section `M | 0.5d`
As a player, I want to see my sport is supported so I feel the app is for me.
- 5 informational cards (matches `sport_types` values in DB):
  - Bóng đá — "5vs5, 7vs7 · Sân cỏ nhân tạo"
  - Cầu lông — "Sân trong nhà · Tiêu chuẩn thi đấu"
  - Pickleball — "Môn mới tại Việt Nam · Dễ học, dễ chơi" (badge: "Đang hot")
  - Tennis — "Sân đơn và đôi · Trong nhà và ngoài trời"
  - Đa năng — "Sân linh hoạt · Nhiều môn trên cùng một sân"
- Responsive grid: 3 columns desktop, 2 columns tablet, 1 column mobile
- Single "Mở app ngay" CTA below all cards

### MKT-005 — App screenshot preview `M | 1d`
As a player, I want to see what the app looks like so I trust it before opening it.
- 4 phone mockup screenshots matching actual app screens:
  1. Map screen — "Sân gần bạn" (green/yellow/red pins, sport filter chips)
  2. Court detail — "Xem sân và giá" (photo carousel, price, amenities)
  3. Slot picker — "Chọn giờ trống" (date tabs + slot grid)
  4. Booking confirmed — "Đặt xong — chờ chủ sân duyệt"
- Scrollable carousel on mobile; 2-up grid on desktop
- CTA at bottom: "Mở app ngay"

### MKT-006 — PWA install instructions `M | 0.5d`
As a player on mobile, I want to add the app to my home screen so it feels like a real app.
- Section: "Cài SportBuddies vào điện thoại — miễn phí, không cần App Store"
- iOS: tap Share → "Add to Home Screen"
- Android: browser menu → "Add to Home Screen" or "Install app"
- Shows correct instructions based on `navigator.userAgent`
- CTA: "Mở app trước, cài sau" for users who want to try first

### MKT-008 — Owner teaser section `M | 0.5d`
As a court owner who scrolled past the player content, I want to see a clear CTA for me.
- Headline: "Bạn là chủ sân?"
- One-liner: "Đăng ký miễn phí — tụi mình mang khách đến sân bạn"
- 3 quick benefit icons (matching actual dashboard features):
  - Nhận thông báo đặt sân ngay lập tức
  - Quản lý lịch sân trực quan theo tuần
  - Xem doanh thu và giờ cao điểm
- CTA: "Đăng ký sân ngay" → `/cho-chu-san`

### MKT-009 — Footer `M | 0.5d`
As a user, I want to find contact and audience-specific links quickly.
- Social: Facebook, TikTok
- Contact: Zalo support number (click-to-Zalo)
- Links: "Chủ sân" → `/cho-chu-san` | "Đại lý / CTV" → `/dai-ly`
- Sport pages: Bóng đá / Cầu lông / Pickleball / Tennis → `/bong-da`, `/cau-long`, `/pickleball`, `/tennis`
- Copyright + "Đặt sân thể thao tại TP.HCM"

---

## EPIC-MKT-2: Owner Acquisition Page
*All owner copy and lead form live at `/cho-chu-san` only — not on homepage.*
**Target: May 2**

### MKT-010 — Owner sign-up page (`/cho-chu-san`) `M | 1d`
As a court owner, I want a page designed for me so I can register without wading through player content.
- Headline: "Lấp đầy giờ trống — miễn phí 3 tháng"
- Owner pain points (matching real problems from PRD):
  - Bỏ lỡ booking vì điện thoại bận
  - Giờ trống không ai biết để đặt
  - Không có khách mới ngoài khách quen
- SpB solutions (matching actual dashboard features):
  - Nhận thông báo tức thì mỗi khi có người đặt sân
  - Duyệt hoặc từ chối booking bằng 1 chạm — số điện thoại khách hiện sau khi duyệt
  - Lịch sân 7 ngày — xem tất cả slot, khoá giờ, tạo lịch cố định hàng tuần
  - Thêm booking tại quầy cho khách walk-in
  - Thống kê doanh thu và giờ cao điểm theo tuần
  - Xuất hiện trên bản đồ SportBuddies cho hàng nghìn người chơi tại TP.HCM
- Lead form: owner name, phone, court name, sport types (multi-select: Bóng đá / Cầu lông / Pickleball / Tennis / Đa năng), district (HCMC dropdown)
  - Writes to `leads` table with `type = owner`; records `utm_source`, `utm_medium`, `utm_campaign`
  - If URL contains `?agent=CODE`, store `agent_code` in hidden field → saved to `leads.agent_code`; used to attribute commission to the referring agent
  - Success: "Cảm ơn! Tụi mình sẽ liên hệ bạn trong 24h"
  - Phone validation: 10 digits, starts with 0
- "Tại sao chọn SpB?": free 3 months / zero setup fee / we bring customers / Zalo support for first 7 days

---

## EPIC-MKT-3: Agent Acquisition Page
*Agents (đại lý / CTV) recruit court owners and earn commission per court onboarded. This page is the primary agent registration entry point.*
**Target: May 2**

### MKT-020 — Agent landing page (`/dai-ly`) `M | 1d`
As a sports community member with a network (coach, group admin, gym owner, sports shop), I want a page that explains the SpB agent program so I can decide to sign up.

- Headline: "Kiếm thu nhập cùng SportBuddies"
- Subheadline: "Giới thiệu sân thể thao cho SpB — nhận 200,000 VND mỗi sân hoạt động. Không cần vốn."
- "Đại lý là ai?" section — 4 target profiles matching `role` options:
  - Huấn luyện viên
  - Trưởng nhóm thể thao
  - Chủ gym / phòng tập
  - Cửa hàng dụng cụ thể thao
- Commission table:

  | Hoạt động | Hoa hồng |
  |---|---|
  | 1 sân đăng ký + hoạt động ≥ 30 ngày | **200,000 VND** |

- 3-step "Cách hoạt động": Đăng ký → SpB liên hệ Zalo trong 24h → Đi gặp sân, nhận hoa hồng cuối tháng
- "Tại sao ngay bây giờ?" — 4 bullets: thị trường mới / pickleball bùng nổ / phí 0 đồng / SpB hỗ trợ trực tiếp
- FAQ section (5 questions):
  1. "Tôi có cần kỹ năng kỹ thuật không?" → Không, chỉ cần gặp trực tiếp chủ sân.
  2. "Tôi có thể là đại lý và chủ sân cùng lúc không?" → Có, hai vai trò hoàn toàn độc lập.
  3. "Khi nào hoa hồng được thanh toán?" → Cuối mỗi tháng, số dư ≥ 200,000 VND.
  4. "Tôi theo dõi kết quả ở đâu?" → Giai đoạn beta: SpB gửi báo cáo hàng tuần qua Zalo.
  5. "Hoa hồng có giới hạn không?" → Không giới hạn số sân được giới thiệu.
- Primary CTA: "Đăng ký làm đại lý ngay" → smooth scrolls to registration form (MKT-021)
- OG tags:
  - `og:title`: "Đại lý SportBuddies — Kiếm thu nhập từ mạng lưới thể thao"
  - `og:description`: "Giới thiệu sân thể thao cho SportBuddies và nhận 200,000 VND mỗi sân. Không cần vốn, chỉ cần mạng lưới."
  - `og:image`: `/images/og-agent.png` (1200×630px, agent-themed branded card)

---

### MKT-021 — Agent registration form `M | 0.5d`
As a prospective agent, I want to register with a simple form so SpB can contact me on Zalo.

- Form fields:
  - Họ và tên (text, required)
  - Số điện thoại / Zalo (tel, required; 10 digits starting with 0)
  - Bạn là (select, required): Huấn luyện viên / Trưởng nhóm thể thao / Chủ gym / Cửa hàng dụng cụ / Khác
  - Mạng lưới của bạn (textarea, optional; placeholder: "Ví dụ: Admin nhóm Pickleball Quận 7, 200 thành viên")
- Writes to `agent_applications` table; records `utm_source`, `utm_medium`, `utm_campaign`
- Success message: "Cảm ơn! Tụi mình sẽ nhắn Zalo cho bạn trong 24 giờ để hướng dẫn các bước tiếp theo."
- PostHog event: `agent_registration_submit`
- Facebook Pixel `Lead` event on submit

---

### MKT-022 — Agent referral link `S | 0.5d`
As an active agent, I want a unique referral link to share with court owners so my introductions are automatically attributed to me for commission tracking.

- Each approved agent assigned a short `agent_code` (e.g. `SPB-A01`) stored in `agent_applications.agent_code`
- SpB team shares link with agent via Zalo: `sportbuddies.vn/cho-chu-san?agent=SPB-A01`
- On page load, `agent` param read from URL → stored in `sessionStorage`
- Passed as hidden field in owner lead form → `leads.agent_code`
- If agent link is shared on social and owner opens it days later: `sessionStorage` may be gone; agent attribution best-effort only (not guaranteed across sessions)
- No agent dashboard in v1 — SpB tracks attribution manually and reports weekly via Zalo

---

## EPIC-MKT-4: SEO & Sport Niche Pages
*Organic reach via per-sport search terms.*
**Target: May 20–21**

### MKT-030 — Bóng đá niche page (`/bong-da`) `S | 0.5d`
As a football player searching Google, I want a dedicated page so I find SpB before competitors.
- SEO targets: "sân bóng đá TPHCM", "đặt sân bóng 5 người quận X", "sân cỏ nhân tạo TPHCM"
- Content: available court types (5vs5, 7vs7), SpB booking flow, live court list filtered by `sport_types @> ['football']`
- `<title>`: "Đặt Sân Bóng Đá TPHCM – SportBuddies"

### MKT-031 — Cầu lông niche page (`/cau-long`) `S | 0.5d`
As a badminton player searching Google, I want a dedicated page so I find SpB before competitors.
- SEO targets: "sân cầu lông TPHCM", "đặt sân cầu lông quận X"
- Content: indoor court info, SpB booking flow, live court list filtered by `sport_types @> ['badminton']`
- `<title>`: "Đặt Sân Cầu Lông TPHCM – SportBuddies"

### MKT-032 — Pickleball niche page (`/pickleball`) `S | 0.5d`
As a pickleball player searching Google, I want a dedicated page so I find SpB before competitors.
- SEO targets: "sân pickleball TPHCM", "đặt sân pickleball quận X"
- Content: intro to pickleball in Vietnam, SpB as best way to book, live court list filtered by `sport_types @> ['pickleball']`
- `<title>`: "Đặt Sân Pickleball TPHCM – SportBuddies"
- OG image with pickleball branding + "Đang hot" badge

### MKT-033 — Tennis niche page (`/tennis`) `S | 0.5d`
As a tennis player searching Google, I want a dedicated page so I find SpB before competitors.
- SEO targets: "sân tennis TPHCM", "đặt sân tennis quận X", "sân tennis trong nhà TPHCM"
- Content: indoor vs outdoor courts, SpB booking flow, live court list filtered by `sport_types @> ['tennis']`
- `<title>`: "Đặt Sân Tennis TPHCM – SportBuddies"

*All sport pages share the same component template — parameterised by sport type.*

---

## EPIC-MKT-5: Analytics & Ad Tracking
*Must ship May 2 with the site.*
**Target: May 2**

### MKT-040 — PostHog tracking `M | 0.5d`
As the growth team, I want to track which sections convert for each audience.
- PostHog in `layout.tsx`
- Events: `page_view`, `cta_click` (with `cta_id` and `audience: customer|owner|agent`), `app_open_click`, `pwa_section_view`, `sport_card_click` (with `sport` property), `agent_registration_submit`
- Env var: `NEXT_PUBLIC_POSTHOG_KEY`

### MKT-041 — Facebook Pixel `M | 0.5d`
As the growth team, I want FB Pixel installed so ads can retarget visitors.
- Fires on page load; `ViewContent` on app CTA click
- `Lead` event on `/cho-chu-san` form submission
- Env var: `NEXT_PUBLIC_FB_PIXEL_ID`

### MKT-042 — UTM capture `M | 0.5d`
As the growth team, I want to know which channel sent each visitor so I can double down on what works.
- Parse `utm_source`, `utm_medium`, `utm_campaign` on load → persist in `sessionStorage`
- Pass all three to `leads` insert (requires `utm_source`, `utm_medium`, `utm_campaign` columns on `leads` table)
- Log to PostHog on CTA click

---

## EPIC-MKT-6: SEO & Performance
*Must pass before May 2 deploy.*
**Target: May 2**

### MKT-050 — Meta & OG tags `M | 0.5d`
As a user sharing the site on Zalo/Facebook, I want link previews to look good.
- `<title>`: "SportBuddies – Đặt sân thể thao tại TP.HCM trong 30 giây"
- `og:image`: 1200×630 branded card (map mockup with colored pins + headline)
- Per-page overrides: `/cho-chu-san`, `/bong-da`, `/cau-long`, `/pickleball`, `/tennis`

### MKT-051 — Lighthouse mobile ≥ 80 `M | 0.5d`
As a player on 4G, I want the page to load fast so I don't bounce.
- Score ≥ 80; all images use `next/image` with WebP + lazy load; no render-blocking JS

### MKT-052 — Sitemap & robots.txt `S | 0.5d`
- `sitemap.xml` at build time includes: `/`, `/cho-chu-san`, `/bong-da`, `/cau-long`, `/pickleball`, `/tennis`
- `robots.txt` allows all crawlers

---

## EPIC-MKT-7: Launch Push (Phase 3 — June 1)
**Target: May 28–31**

### MKT-060 — Featured courts grid `M | 1d`
As a player on launch day, I want to see real courts so I trust supply exists.
- Grid of 3–6 informational court cards: photo, name, district, sport type badges
- Pulled from `courts(status=approved)` ordered by `created_at DESC`
- Each card shows sport type badges matching `sport_types[]` values
- No per-court links; single "Mở app để đặt sân" CTA below the grid

### MKT-061 — Live booking counter `S | 0.5d`
As a new visitor, I want to see real activity so the platform feels alive.
- "X lượt đặt sân trong 7 ngày qua" — pulled from Supabase `bookings` count

### MKT-062 — Launch banner `S | 0.5d`
- Dismissible top banner: "SportBuddies ra mắt chính thức 01/06/2026"
- Toggled via `NEXT_PUBLIC_SHOW_LAUNCH_BANNER=true` (enable May 31)

---

## Build Schedule

| Epic | Stories | Days | Target |
|---|---|---|---|
| EPIC-MKT-1: Core Landing (player) | 8 | 2 | May 1–2 |
| EPIC-MKT-2: Owner Page | 1 | 1 | May 2 |
| EPIC-MKT-3: Agent Page | 3 | 1.5 | May 2 |
| EPIC-MKT-5: Analytics | 3 | 1 | May 2 |
| EPIC-MKT-6: SEO & Perf | 3 | 1 | May 2 |
| EPIC-MKT-4: SEO Niche (4 sport pages) | 4 | 1.5 | May 20–21 |
| EPIC-MKT-7: Launch Push | 3 | 1.5 | May 28–31 |
| **Total** | **25** | **~9.5** | — |

**Critical path for May 2:**
MKT-001 → MKT-008 → MKT-010 → MKT-040 → MKT-050 → deploy

## Schema dependencies

> Canonical schema for `leads` and `agent_applications` (including all columns for sport_types, agent_code, UTM fields) is in **[`backend_core/schema.sql`](../backend_core/schema.sql)** tables 1.11 and 1.12. Do not maintain a duplicate here.

## Priority legend
- `M` = MUST (blocks May 2 launch)
- `S` = SHOULD (adds conversion; build after MUSTs are done)

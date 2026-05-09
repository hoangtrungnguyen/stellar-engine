# SportBuddies (SpB) — Product Requirements Document
### For Business Stakeholders

**Version:** 1.1
**Date:** 2026-05-06
**Owner:** htnguyen
**Launch:** 2026-06-01
**Budget:** 25,000,000 VND
**Authoritative source for product scope.** See `backend_core/schema.sql` for the database schema.

---

## Executive Summary

SportBuddies (SpB) is a sports marketplace platform for Ho Chi Minh City. It connects sports court owners with players looking for available courts, and recruits agents (đại lý / CTV) to onboard new courts. Players can find and book open courts in minutes. Court owners get a simple tool to manage bookings and fill idle time slots. Agents earn commission for every court they bring onto the platform.

**The business goal for launch:** 10 active courts onboarded, 50+ bookings completed, 5+ agents registered, proof of demand before scaling.

---

## The Problem

### For players
- No easy way to know which courts have open slots right now
- Calling courts one by one wastes 15–30 minutes
- Popular booking apps are complicated, have few courts listed, and offer no promotions
- Hard to find courts for newer sports like pickleball

### For court owners
- Bookings come in via phone calls — easy to miss, easy to double-book
- No visibility into which time slots stay empty week after week
- No digital presence to attract new customers beyond word of mouth
- Existing apps require complicated setup with little benefit

### For agents (sports community members with networks)
- No way to monetise their network (coaches, group admins, gym owners, sports shops)
- Sports community trust → strong introduction channel that competitors don't tap

---

## The Solution

Three connected products + an agent program that together form the SpB platform:

### 1. Landing Page (`sportbuddies.vn`)
A public-facing website that explains SpB to all three audiences. Includes:
- Homepage for players (CTA: "Mở app ngay")
- `/cho-chu-san` — owner sign-up page with lead form
- `/dai-ly` — agent registration page with commission terms
- Per-sport SEO pages (`/bong-da`, `/cau-long`, `/pickleball`, `/tennis`)

### 2. Customer App (web, mobile post-launch)
A web application for players, accessible from any browser on phone or desktop. v1 ships as a Flutter Web PWA; native iOS/Android apps come after launch using the same codebase. Core experience:
- Open the app → see a map of nearby courts
- Green pin = court has open slots, red pin = fully booked
- Tap a court → see photos, pricing, available time slots
- Pick a time → confirm booking → pay cash at the court
- Under 60 seconds from open to booked

### 3. Owner Dashboard (web)
A browser-based tool for court owners. Core experience:
- Log in → see today's bookings
- Approve or reject new requests (with one tap)
- On approval, player's phone number is revealed so owner can call to confirm
- Edit schedule and block out unavailable slots
- See weekly booking summary

### 4. Agent Program (operations + minimal product surface)
- Agents register at `/dai-ly` with name, phone (Zalo), role, and network description
- SpB approves agent and assigns a unique `agent_code` (e.g. `SPB-A01`) for attribution
- Agent shares referral link `sportbuddies.vn/cho-chu-san?agent=SPB-A01` with court owners
- When an agent-referred court is approved and active for ≥30 days, agent earns 200,000 VND commission
- v1: tracking is manual (SpB team reports weekly via Zalo); agent dashboard ships post-launch

**In all cases, payment for court bookings happens in cash at the venue.** No online payment in this version. Agent commissions paid via bank transfer end of month.

---

## Target Users

### Players ("Người chơi")
- Ages 18–40, live or work in HCMC
- Play sports 1–3 times per week
- Currently find courts via Facebook groups or Google Maps
- Pain: don't know which courts are available tonight without calling around

### Court Owners ("Chủ sân")
- Own or manage 1–3 sports courts in HCMC
- Ages 30–55, Vietnamese-speaking
- Currently manage bookings by phone and paper notebook
- Pain: no-shows, idle off-peak hours, no way to reach new customers

### Agents ("Đại lý / CTV")
- Anyone with a network in the HCMC sports community: coaches, group admins, gym owners, sports equipment shops
- Pain: no way to monetise their network
- Motivation: 200,000 VND per court onboarded + "Đại lý nổi bật" social-status badge

---

## Geographic Scope

**Launch city:** Ho Chi Minh City only.
**Launch area:** 1–2 districts (to be decided by 2026-04-30). Concentrate supply in a small area first so the map looks full, not empty.
**Sports covered:** Football (5-a-side, 7-a-side), Badminton, Pickleball, Tennis, Đa năng (multi-purpose courts).

Expansion to other districts and cities happens after launch when demand is proven.

---

## Success Metrics

| Audience | What we measure | Target by June 1, 2026 |
|---|---|---|
| Owners | Courts signed up | ≥ 10 |
| Owners | Courts with at least 1 booking per week | ≥ 5 |
| Owners | Court owner retention after 7 days | ≥ 60% |
| Players | Total bookings during beta (May 22–31) | ≥ 50 |
| Players | Bookings where player actually showed up | ≥ 30 |
| Players | Players who come back within 7 days | ≥ 25% |
| Agents | Agents registered | ≥ 5 |
| Agents | Agents active (≥1 court visit in 30 days) | ≥ 3 |
| Agents | Courts onboarded via agents | ≥ 3 |

**If fewer than 5 courts are active by May 31, we delay the public launch and revisit the court acquisition strategy.**

---

## Timeline

| Date | What happens |
|---|---|
| April 30 | Final scope agreed. Target districts chosen. |
| May 1 | Website design starts |
| May 2 | Website goes live (homepage + `/cho-chu-san` + `/dai-ly`). Name cards printed. **Court owner outreach + agent recruitment begin.** |
| May 3–17 | All three products built (15 working days) |
| May 18–21 | In-person visits to onboard first 3 courts. Real-device testing. |
| May 22–31 | Closed beta: 10 courts + 30–50 invited players test the platform |
| June 1 | Public launch event |

**The most important activity is not coding — it is walking into courts between May 2 and May 21 and convincing owners to join.** Technology is ready by May 17. Supply is the bottleneck. Agents are the lever for parallelising court acquisition.

---

## Budget Breakdown

| Item | Amount (VND) |
|---|---|
| App infrastructure (hosting, DB, maps, email, FCM) | 2,500,000 |
| Name cards + printed flyers for owner outreach | 500,000 |
| Beta user incentive (50 free bookings to seed activity) | 2,500,000 |
| Agent commissions (Phase 1: ~12 courts × 200,000 VND) | 2,500,000 |
| Contingency buffer | 1,000,000 |
| Build / paid SaaS reserve | 3,000,000 |
| **Operations subtotal** | **12,000,000** |
| **Marketing & launch** | **13,000,000** |
| **Grand total** | **25,000,000** |

Marketing breakdown:
- Facebook Ads (test + small scale): 4,000,000
- Video + content creation (TikTok / Reels): 3,000,000
- Offline outreach (transport, printing, meals): 3,000,000
- Launch push + buffer: 3,000,000

Notes:
- AI-assisted development (Claude Code) is already covered by existing subscription — no additional cost
- Design is handled by AI tools (Claude / v0) — no designer hire
- No payment processing fees in v1 (cash at venue; agent payouts via bank transfer)
- Twilio SMS removed — push notifications use Firebase Cloud Messaging (free tier)

---

## What We Are NOT Building (v1)

These are confirmed out of scope for the June 1 launch:

- Online payment (VNPay, Momo, ZaloPay) — cash at venue only
- In-app chat between players and owners
- Player ratings and reviews
- Partner matching ("find someone to play with") — handled by play-together access policy on existing slots, not as a standalone feature
- Tournament organisation
- Loyalty points or rewards
- Multiple cities or provinces
- AI-powered court suggestions
- Group bookings
- Native iOS/Android apps (web-first PWA; native apps post-launch using same Flutter codebase)
- Phone OTP login (replaced with email/password + Gmail OAuth)
- Agent self-service dashboard (agent tracking is manual via Zalo in v1; dashboard ships post-launch)

These features are prioritised for v2 based on what users ask for after launch.

---

## Business Risks

| Risk | How likely | Impact | What we'll do |
|---|---|---|---|
| Not enough courts sign up by May 31 | High | Critical | Start outreach + agent recruitment May 2. Visit courts in person. Offer 3 months free featured listing. |
| Court owners find the app too hard to use | High | High | Provide Zalo support number. Do in-person setup for first 3 courts. Keep UI extremely simple. |
| Players show up but courts have no open slots | Medium | High | Confirm slot availability in person before seeding courts into the app. |
| No-shows damage owner trust in the platform | High | Medium | Track no-shows. Introduce deposit system in v2. |
| Players expect online payment | Medium | Low | Label "Pay at venue" clearly on every booking confirmation. |
| Marketing budget spent with no sign-ups | Medium | High | Run FB ads geo-targeted to the 2 launch districts only. Stop ads that don't convert within 3 days. |
| Players prefer native app over web PWA | Medium | Medium | Track user feedback; if >50% request native app, accelerate mobile build post-launch. |
| Agents fail to deliver introductions (no shows / low quality leads) | Medium | Medium | Vet agents during onboarding (require active sports network proof). Provide pitch script + flyers. Pay only on courts active ≥30 days. |
| Commission disputes (agent claims attribution) | Low | Medium | All attribution via `leads.agent_code` + `agent_applications.agent_code`. Manual review for ambiguous cases. |
| FCM push reminders don't reach all players (web/iOS Safari) | Medium | Low | Accept as v1 trade-off; add Resend email-reminder fallback in v2 if retention drops |

---

## Open Decisions (by April 30)

1. Which 2 HCMC districts to seed first?
2. Who is responsible for walking into courts with name cards? (Critical role — must be assigned to a person, not left open.)
3. What is the SpB owner pricing model post-beta? (Free during beta; commission, subscription, or freemium after?)
4. Final domain name: `sportbuddies.vn` or alternative?
5. Agent vetting threshold — what constitutes an "active sports network" sufficient to approve an agent application?

---

## Document Map

| Document | Purpose |
|---|---|
| `business/PRD_business.md` (this file) | **Authoritative product scope** |
| `business/TECHNICAL_SPEC.md` | Architecture, stack decisions |
| `backend_core/schema.sql` | Canonical DB schema |
| `backend_core/backend_stories.md` | Backend epics + endpoints |
| `customer_app/customer_stories.md` | Customer app stories (Flutter) |
| `owner_dashboard/owner_stories_v2.md` | Owner dashboard stories (Flutter) |
| `web_intro/stories.md` | Marketing site stories (Next.js) |
| `a2a/agent_stories.md` | Read-only public discovery API |
| `design/{colors,typography,spacing,components}.md` | Design system |

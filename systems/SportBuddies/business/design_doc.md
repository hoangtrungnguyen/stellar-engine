# Summary

\- Map (tìm kiếm, hiển thị sân)  
\- Đặt sân 1 chạm ( Hiển thị sân đã đặt, đang đặt, ...)  
\- Theo dõi lịch của sân (Trong này sẽ có phần comment để họ có thể liên hệ với những người muốn chơi cùng)  
\- Đăng ký/ đăng nhập, profile, setting 

## **1\. Mục tiêu sản phẩm**

Nền tảng marketplace giúp:

* Người chơi **tìm & đặt sân nhanh dưới 60s**  
* Chủ sân **lấp đầy khung giờ trống**

**Goal launch (01/06/2026):**

* ≥ 10 sân onboard  
* ≥ 50 booking  
* Validate demand thực tế

---

## **2\. Vấn đề chính**

### **Người chơi**

* Không biết sân nào còn slot → phải gọi từng nơi (15–30 phút)  
* Không có nền tảng tập trung, đặc biệt với môn mới

### **Chủ sân**

* Quản lý thủ công → dễ miss / double booking  
* Nhiều giờ trống không được khai thác  
* Không có kênh thu hút khách mới

---

## **3\. Giải pháp (Core Product)**

Hệ sinh thái gồm 3 phần:

### **(1) Landing Page**

* Giới thiệu sản phẩm  
* Thu hút chủ sân đăng ký miễn phí

### **(2) Customer App (Web v1)**

Flow chính:

* Mở app → xem map sân gần  
* Màu:  
  * Xanh: còn slot  
  * Đỏ: full  
* Click sân → xem:  
  * Ảnh, giá, khung giờ  
* Chọn giờ → đặt → trả tiền tại sân

**Screens:**

* Map  
* Court Detail  
* Booking

### **(3) Owner Dashboard**

* Xem booking theo ngày  
* Approve / reject nhanh  
* Quản lý lịch sân  
* Xem thống kê tuần

---

## **4\. Tính năng cốt lõi (v1 – MUST HAVE)**

* Map hiển thị sân  
* Lọc theo vị trí / khoảng cách  
* Xem slot trống realtime  
* Đặt sân 1 chạm  
* Lịch sân \+ trạng thái booking  
* Auth \+ profile  
* Dashboard cho chủ sân

---

## **5\. User mục tiêu**

### **Người chơi**

* 18–40 tuổi  
* Chơi thể thao 1–3 lần/tuần  
* Hiện dùng Facebook / Google Maps để tìm sân

### **Chủ sân**

* 30–55 tuổi  
* Quản lý thủ công  
* Pain: no-show, giờ trống, thiếu khách

---

## **6\. Phạm vi (Scope v1)**

* Thành phố: TP.HCM  
* Khu vực: 1–2 quận (focus để có density)  
* Môn: bóng đá, cầu lông, pickleball (ưu tiên)

---

## **7\. Success Metrics**

* ≥ 10 sân onboard  
* ≥ 5 sân có booking mỗi tuần  
* ≥ 50 booking (beta)  
* ≥ 25% user quay lại  
* ≥ 60% chủ sân active sau 7 ngày

---

## **8\. Out of Scope (v1)**

Không build:

* Thanh toán online  
* Chat  
* Tìm partner  
* Review / rating  
* Native app  
* Loyalty / AI recommend

---

## **9\. Rủi ro chính**

* Không đủ sân → **critical risk**  
* Chủ sân không dùng được app → cần UI cực đơn giản  
* No-show → ảnh hưởng trust  
* Marketing không hiệu quả

**Insight quan trọng:**

Bottleneck không phải tech, mà là **onboard supply (chủ sân)**

---

## **10\. Chiến lược triển khai**

* Build nhanh (≤ 15 ngày)  
* Đi trực tiếp gặp chủ sân (offline sales)  
* Seed supply trước, rồi mới scale demand  
* Beta kín trước launch

---

## **11\. Nguyên tắc sản phẩm**

* Cực kỳ đơn giản (no friction)  
* Booking \< 60s  
* Ưu tiên supply trước demand  
* Web-first → validate → scale

# PRD Ver 2

# **SportBuddies (SpB) — Product Requirements Document**

### **For Business Stakeholders**

\*\*Version:\*\* 1.0  
\*\*Date:\*\* 2026-04-29  
\*\*Owner:\*\* htnguyen  
\*\*Launch:\*\* 2026-06-01  
\*\*Budget:\*\* 26,000,000 VND

\---

## **Executive Summary**

SportBuddies (SpB) is a sports marketplace platform for Ho Chi Minh City. It connects sports court owners with players looking for available courts. Players can find and book open courts in minutes. Court owners get a simple tool to manage bookings and fill idle time slots.

\*\*The business goal for launch:\*\* 10 active courts onboarded, 50+ bookings completed, proof of demand before scaling.

\---

## **The Problem**

### **For players**

\- No easy way to know which courts have open slots right now  
\- Calling courts one by one wastes 15-30 minutes  
\- Popular booking apps are complicated, have few courts listed, and offer no promotions  
\- Hard to find courts for newer sports like pickleball

### **For court owners**

\- Bookings come in via phone calls — easy to miss, easy to double-book  
\- No visibility into which time slots stay empty week after week  
\- No digital presence to attract new customers beyond word of mouth  
\- Existing apps require complicated setup with little benefit

\---

## **The Solution**

Three connected products that together form the SpB platform:

### **1\. Landing Page (website)**

A public-facing website that explains SpB to both players and court owners. The main goal is to convince court owners to sign up their court for free.

### **2\. Customer App (web, mobile post-launch)**

A web application for players, accessible from any browser on phone or desktop. v1 ships as a web app; native iOS/Android apps come after launch using the same codebase. Core experience:  
\- Open the app → see a map of nearby courts  
\- Green pin \= court has open slots, red pin \= fully booked  
\- Tap a court → see photos, pricing, available time slots  
\- Pick a time → confirm booking → pay cash at the court  
\- Under 60 seconds from open to booked

### **Screens**

- Map  
- Court’s detail  
- Court’s booking

### **3\. Owner Dashboard (web)**

A browser-based tool for court owners. Core experience:  
\- Log in → see today's bookings  
\- Approve or reject new requests (with one tap)  
\- On approval, player's phone number is revealed so owner can call to confirm  
\- Edit schedule and block out unavailable slots  
\- See weekly booking summary

\*\*In all cases, payment happens in cash at the venue.\*\* No online payment in this version — keeping it simple.

\---

## **Target Users**

### **Court Owners ("Chủ sân")**

\- Own or manage 1–3 sports courts in HCMC  
\- Ages 30–55, Vietnamese-speaking  
\- Currently manage bookings by phone and paper notebook  
\- Pain: no-shows, idle off-peak hours, no way to reach new customers

### **Players ("Người chơi")**

\- Ages 18–40, live or work in HCMC  
\- Play sports 1–3 times per week  
\- Currently find courts via Facebook groups or Google Maps  
\- Pain: don't know which courts are available tonight without calling around

\---

## **Geographic Scope**

\*\*Launch city:\*\* Ho Chi Minh City only.  
\*\*Launch area:\*\* 1–2 districts (to be decided by 2026-04-30). Concentrate supply in a small area first so the map looks full, not empty.  
\*\*Sports covered:\*\* Football (5-a-side, 7-a-side), badminton, pickleball. Tennis if available.

Expansion to other districts and cities happens after launch when demand is proven.

\---

## **Success Metrics**

These are the numbers that define a successful launch:

| What we measure | Target by June 1, 2026 |
| :---- | :---- |
| Courts signed up | ≥ 10 |
| Courts with at least 1 booking per week | ≥ 5 |
| Total bookings during beta (May 22–31) | ≥ 50 |
| Bookings where player actually showed up | ≥ 30 |
| Players who come back within 7 days | ≥ 25% |
| Court owners still using the app after 7 days | ≥ 60% |

\*\*If fewer than 5 courts are active by May 31, we delay the public launch and revisit the court acquisition strategy.\*\*

\---

## **Timeline**

| Date | What happens |
| :---- | :---- |
| April 30 | Final scope agreed. Target districts chosen. |
| May 1 | Website design starts |
| May 2 | Website goes live. Name cards printed. Court owner outreach begins. |
| May 3–17 | All three products built (15 working days) |
| May 18–21 | In-person visits to onboard first 3 courts. Real-device testing. |
| May 22–31 | Closed beta: 10 courts \+ 30–50 invited players test the platform |
| June 1 | Public launch event |

\*\*The most important activity is not coding — it is walking into courts between May 2 and May 21 and convincing owners to join.\*\* Technology is ready by May 17\. Supply is the bottleneck.

\---

## **Budget Breakdown**

| Item | Amount (VND) |
| :---- | :---- |
| App infrastructure (hosting, database, maps, email, SMS) | 2,500,000 |
| Name cards \+ printed flyers for owner outreach | 500,000 |
| Beta user incentive (50 free bookings to seed activity) | 2,500,000 |
| Contingency buffer | 1,500,000 |
| Build cost | 5,000,000 |
| **Build total** | **13,000,000** |
| **Marketing & launch event (FB ads, signage, PR)** | **13,000,000** |
| **Grand total** | **26,000,000** |

Notes:  
\- AI-assisted development (Claude Code) is already covered by existing subscription — no additional cost.  
\- Design is handled by AI tools — no designer hire.  
\- No payment processing fees in v1 (cash at venue).

\---

## **What We Are NOT Building (v1)**

These are confirmed out of scope for the June 1 launch:

\- Online payment (VNPay, Momo, ZaloPay)  
\- In-app chat between players and owners  
\- Player ratings and reviews  
\- Partner matching ("find someone to play with")  
\- Tournament organisation  
\- Loyalty points or rewards  
\- Multiple cities or provinces  
\- AI-powered court suggestions  
\- Group bookings  
\- Native iOS/Android apps (web first; native apps post-launch)

These features are prioritised for v2 based on what users ask for after launch.

\---

## **Business Risks**

| Risk | How likely | Impact | What we'll do |
| :---- | :---- | :---- | :---- |
| Not enough courts sign up by May 31 | High | Critical | Start outreach on May 2, not May 22\. Visit courts in person. Offer 3 months of free featured listing. |
| Court owners find the app too hard to use | High | High | Provide Zalo support number. Do in-person setup for first 3 courts. Keep the UI extremely simple. |
| Players show up but courts have no open slots | Medium | High | Confirm slot availability in person before seeding courts into the app. |
| No-shows damage owner trust in the platform | High | Medium | Track no-shows. Introduce deposit system in v2. |
| Players expect online payment | Medium | Low | Label "Pay at venue" clearly on every booking confirmation. |
| Marketing budget spent with no sign-ups | Medium | High | Run FB ads geo-targeted to the 2 launch districts only. Stop ads that don't convert within 3 days. |
| Players prefer native app over web | Medium | Medium | Track user feedback; if \>50% request native app, accelerate mobile build post-launch. |

\---

## **Open Decisions (by April 30\)**

1\. Which 2 HCMC districts to seed first?  
2\. Who is responsible for walking into courts with name cards? (Critical role — must be assigned to a person, not left open.)


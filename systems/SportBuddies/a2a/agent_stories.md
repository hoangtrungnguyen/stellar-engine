# A2A — Agent-to-API Stories

**What is A2A?**
Read-only API surface for external agents (AI agents, bots, integrations) to discover courts and available slots on the SportBuddies platform. No write operations. No auth required beyond the public anon key.

**Scope:** Discovery only — courts and slots. No bookings, no user data, no owner data.

**Auth:** Supabase anon key in `Authorization: Bearer <anon_key>` header. RLS ensures only `status = approved` courts and `status = open` slots are visible.

---

### A2A-001 — Discover courts · `M`
An agent wants to find sports courts by location and sport type.

**Endpoint:** `GET /a2a/courts`

**Query params:**
| Param | Type | Description |
|---|---|---|
| `lat` | float | Centre latitude |
| `lng` | float | Centre longitude |
| `radius_km` | int | 1 / 3 / 5 (default 5) |
| `sport` | string | `football` / `badminton` / `pickleball` / `tennis` / `multi` |
| `date` | date | Filter to courts with ≥1 open slot on this date (optional) |

**Response:**
```json
[
  {
    "id": "uuid",
    "name": "Sân Bóng Đá Quận 7",
    "address": "123 Nguyễn Văn Linh, Quận 7, TP.HCM",
    "lat": 10.732,
    "lng": 106.721,
    "sport_types": ["football"],
    "price_per_hour": 150000,
    "distance_km": 1.2,
    "has_open_slots_today": true
  }
]
```

---

### A2A-002 — Discover available slots · `M`
An agent wants to see open time slots for a specific court.

**Endpoint:** `GET /a2a/courts/{court_id}/slots`

**Query params:**
| Param | Type | Description |
|---|---|---|
| `date` | date | Target date (default: today) |
| `from` | date | Range start (use with `to`) |
| `to` | date | Range end — max 7 days span |

**Response:**
```json
[
  {
    "id": "uuid",
    "start_at": "2026-05-06T13:00:00+07:00",
    "end_at": "2026-05-06T14:00:00+07:00",
    "status": "open",
    "price_per_hour": 150000
  }
]
```

- Only `status = open` slots returned — booked/blocked slots omitted
- Sorted by `start_at ASC`

---

## Constraints

- Read-only — no POST / PATCH / DELETE
- No user data, no booking data, no owner contact info exposed
- Rate limit: 60 requests/minute per IP
- Both endpoints return `[]` (not 404) when no results match

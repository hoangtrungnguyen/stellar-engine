# Court Booking Spec

Intro paragraph that sits under H1 with no further nesting yet.

## Epic 1: Court Booking

**UI/UX Design:**
- [Figma — Booking flow](https://figma.com/x)
- design/booking-mockup.png

### US-01 — Pick a court

**As a** customer,
**I want to** browse available courts,
**so that** I can pick one.

**Acceptance Criteria:**
- Map shows pins within 5 km
- Pin tap opens detail sheet

```python
def render_map():
    return goong.tiles()
```

### US-02 — Reserve a court

Reservation flow paragraph.

| Field | Type |
|-------|------|
| start | datetime |
| end | datetime |

## Epic 2: Cancellations

Brief paragraph only — no stories.

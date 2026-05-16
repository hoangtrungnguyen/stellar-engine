# Court Booking Spec

Intro paragraph that sits under H1 with no further nesting yet.

## Epic 1: Court Booking

### US-01 — Pick a court
As a customer, I want to browse available courts on a map, so that I can pick one near me.

- Render the map widget
- Wire location services
- Fetch courts within radius

#### Acceptance Criteria
- Map shows pins within 5 km of current location
- Pin colour reflects availability (green = open, red = booked)
- Tapping a pin opens the court detail sheet

#### UI/UX Design
- [Figma — Booking flow](https://figma.com/file/XXX/booking)
- `design/booking-mockup.png`
- Map pin shape: 32×40px teardrop, white 1.5px outline

### US-02 — Reserve a court
As a customer, I want to reserve a slot, so that the court is held for me.

```python
def reserve(slot_id):
    return atomic_select_for_update(slot_id)
```

- Confirm slot via SELECT FOR UPDATE
- Send confirmation email

| Field | Type |
|-------|------|
| start | datetime |
| end | datetime |

## Epic 2: Cancellations

Brief paragraph only — no stories.

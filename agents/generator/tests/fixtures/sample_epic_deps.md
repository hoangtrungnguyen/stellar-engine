# Demo system

Intro paragraph for the demo spec.

## Authentication

Login + signup flows.

## Court Booking

Pick + reserve a court.

## Cancellations

Refund window + audit log.

## Epic dependencies

```mermaid
graph TD
  A[Authentication] --> B[Court Booking]
  B --> C[Cancellations]
```

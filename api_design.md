# API Design: Bee Activity & Trip Submission

This document specifies the minimal public API surface for the conference demo application. It focuses on two feature domains:

1. Bee activity discovery (derived phenology) via a single JSON endpoint plus a chart image endpoint.
2. Submission and retrieval of bee watching (survey) trips with intentionally complex human / free‑form input to highlight testing edge cases.

All endpoints are read-only except trip creation. No authentication layer is defined here (assumed open for demo). All timestamps are ISO 8601 UTC.

---
## Conventions

Field | Meaning
------|--------
`taxon_id` | Internal numeric identifier of the bee species.
`activity_score` | Normalized aggregate activity (0–1) for the requested date window at/near the provided location.
`month` | Integer 1–12 (Jan=1).
`meta` | Standard envelope for echoing query parameters and lightweight telemetry.

---
## 1. GET /bees/active

Returns species predicted (via precomputed phenology curves) to be seasonally active within a time window and near a geographic location.

### Query Parameters
Parameter | Type | Required | Default | Notes
----------|------|----------|---------|------
`lat` | float | yes | — | Latitude (rounded internally).
`lon` | float | yes | — | Longitude.
`radius_km` | float | no | 25 | Search radius (km). Simple great‑circle filter; small values (≤50) recommended. If omitted, uses default.
`start_date` | date (YYYY-MM-DD) | yes | — | Inclusive.
`end_date` | date (YYYY-MM-DD) | yes | — | Inclusive; must be >= start_date; max window (e.g., 31 days) enforced.
`limit` | int | no | 25 | Max 100.
`min_activity` | float | no | 0.05 | Filters out very low predicted presence.

### 200 Response (without `include_profile`)
```json
{
  "data": [
    {
      "taxon_id": 12345,
      "scientific_name": "Megachile perihirta",
      "common_name": "Western Leafcutter Bee",
      "activity_score": 0.27,
      "peak_month": 7
    },
    {
      "taxon_id": 23456,
      "scientific_name": "Osmia lignaria",
      "common_name": "Blue Orchard Bee",
      "activity_score": 0.19,
      "peak_month": 4
    }
  ]
}
```

---
## 2. GET /bees/phenology-chart/{taxon_id}

Returns an image (PNG default) visualizing the monthly activity curve for a species.

### Query Parameters
Parameter | Type | Default | Notes
----------|------|---------|------
`highlight_window` | bool | true | Shade active window.
`width` | int | 640 | Clamp 320–1400.
`height` | int | 360 | Clamp 240–1000.
`format` | string | `png` | `png` or `svg`.

### Response
- **200** image/png (or image/svg+xml) with headers:
  - `X-Phenology-Summary`: Short textual summary (peak, window, coverage)
- **304** Not Modified (If-None-Match provided and matches)
- **404** JSON if taxon not found
- **422** JSON for invalid params

No JSON body on success (binary image stream).

### Summary Header Example
```
X-Phenology-Summary: Megachile perihirta peak Jul; window May–Aug (82% coverage)
```

---
## 3. POST /trips

Create a new bee watching / survey trip with complex free‑form input to demonstrate validation and sanitization.

### Request Body
```json
{
  "event_name": "Spring Solstice Native Bee Bioblitz – Año Nuevo",
  "organizers": [
    {"display_name": "María-José O’Neill", "role": "lead"},
    {"display_name": "Dr. A. J. van der Meer", "role": "taxonomist"}
  ],
  "address_text": "2500 Long Winding Rd, Cabin B\nOff Hwy 9 after MM 12.5\nSanta Cruz Mountains, CA",
  "country_hint": "US",
  "start_time": "2025-04-12T08:30:00Z",
  "end_time": "2025-04-12T15:00:00Z",
  "approx_latitude": 37.090347,
  "approx_longitude": -121.912345,
  "positional_accuracy_m": 750,
  "contact_emails": ["field-team+april@nativebees.example"],
  "notes": "Focus: early emergence of Osmia spp. <script>alert('x')</script>"
}
```

### Validation Rules (non-exhaustive)
- `end_time` > `start_time` and duration ≤ 24h.
- At least one organizer.
- Each organizer display_name length 1–120 chars; role length ≤ 40.
- `approx_latitude` / `approx_longitude` within California bounding region (optional soft check, else generic lat/lon range).
- `notes` length ≤ 5000 chars; sanitized (script/style tags removed).

### 201 Response
```json
{
  "id": 42,
  "event_slug": "spring-solstice-native-bee-bioblitz-ano-nuevo",
  "event_name": "Spring Solstice Native Bee Bioblitz – Año Nuevo",
  "time_window": {"start_time": "2025-04-12T08:30:00Z", "end_time": "2025-04-12T15:00:00Z", "duration_hours": 6.5},
  "location": {"approx_latitude": 37.0903, "approx_longitude": -121.9123, "positional_accuracy_m": 750},
  "organizers": [
    {"original": "María-José O’Neill", "normalized": "Maria-Jose O'Neill", "has_diacritics": true, "role": "lead"},
    {"original": "Dr. A. J. van der Meer", "normalized": "Dr. A. J. van der Meer", "has_diacritics": false, "role": "taxonomist"}
  ],
  "address": {"lines": ["2500 Long Winding Rd, Cabin B", "Off Hwy 9 after MM 12.5", "Santa Cruz Mountains, CA"], "country": "US"},
  "notes_sanitized": "Focus: early emergence of Osmia spp.",
  "warnings": ["notes: script tags removed"],
  "created_at": "2025-10-10T15:00:00Z"
}
```

---
## 4. GET /trips/{id}

Retrieve full normalized representation of a trip.

### 200 Response (excerpt)
```json
{
  "id": 42,
  "event_name": "Spring Solstice Native Bee Bioblitz – Año Nuevo",
  "event_slug": "spring-solstice-native-bee-bioblitz-ano-nuevo",
  "organizers": [...],
  "address": {"lines": ["2500 Long Winding Rd, Cabin B", "Off Hwy 9 after MM 12.5", "Santa Cruz Mountains, CA"], "country": "US"},
  "notes": "Focus: early emergence of Osmia spp.",
  "created_at": "2025-10-10T15:00:00Z"
}
```

---
## 5. GET /trips

List trips with optional filters.

### Query Parameters
Parameter | Type | Default | Notes
----------|------|---------|------
`since` | date | — | Filter start_time >= since.
`before` | date | — | Filter start_time < before.

### 200 Response
```json
{
  "meta": {"query": {"since": "2025-04-01"}, "count": 2},
  "data": [
    {"id": 42, "event_name": "Spring Solstice Native Bee Bioblitz – Año Nuevo", "start_time": "2025-04-12T08:30:00Z"},
    {"id": 43, "event_name": "Urban Pollinator Walk", "start_time": "2025-05-03T16:00:00Z"}
  ]
}
```

---
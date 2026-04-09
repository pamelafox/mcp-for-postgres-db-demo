# Data Ingestion & Phenology Precomputation Guide

This document explains how to transform a raw iNaturalist CSV export (example header shown below) into the internal tables used by the demo API (`/bees/active`, phenology chart, and trip endpoints). The trip submission feature is independent; this guide covers only biodiversity observation ingestion and phenology derivation.

## 1. Source CSV Example

```
id,uuid,observed_on_string,observed_on,time_observed_at,time_zone,user_id,user_login,user_name,created_at,updated_at,quality_grade,license,url,image_url,sound_url,tag_list,description,num_identification_agreements,num_identification_disagreements,captive_cultivated,oauth_application_id,place_guess,latitude,longitude,positional_accuracy,private_place_guess,private_latitude,private_longitude,public_positional_accuracy,geoprivacy,taxon_geoprivacy,coordinates_obscured,positioning_method,positioning_device,place_town_name,place_county_name,place_state_name,species_guess,scientific_name,common_name,iconic_taxon_name,taxon_id,taxon_order_name,taxon_superfamily_name,taxon_family_name,taxon_subfamily_name,taxon_tribe_name,taxon_genus_name,taxon_species_name,field:interaction->visited flower of
```

Only a subset is required; most columns are dropped to reduce storage, privacy risk, and parsing cost.

## 2. Target Tables (Minimal)

We enable PostGIS for radius queries for `/bees/active`. Enable once per database:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

### observations
| Column | Type | Source / Logic | Notes |
|--------|------|----------------|-------|
| observation_id | BIGINT PK | `id` | Unique per observation |
| taxon_id | BIGINT FK | `taxon_id` | Maps to species table |
| observed_date | DATE | `observed_on` | Parsed as date |
| observed_year | SMALLINT | EXTRACT(YEAR) | For yearly stats / shift calculations (future) |
| observed_month | SMALLINT | EXTRACT(MONTH) | 1–12 |
| latitude | REAL | `latitude` rounded (e.g. 3 decimals) | NULL if missing |
| longitude | REAL | `longitude` rounded | NULL if missing |
| geom | GEOGRAPHY(Point,4326) | ST_SetSRID(ST_MakePoint(longitude, latitude),4326) | Only if lat/lon not null |
| coordinates_obscured | BOOLEAN | `coordinates_obscured OR geoprivacy IS NOT NULL` | Conservative masking flag |
| positional_accuracy | INTEGER NULL | COALESCE(`positional_accuracy`, `public_positional_accuracy`) | Optional filter |
| quality_grade | TEXT | `quality_grade` | Filter to `research` for phenology |
| license | TEXT | `license` | Per observation licensing |
| observer_hash | TEXT | SHA256(salt + user_id) | Salt stored outside repo; uses stable numeric user_id instead of mutable login |
| county | TEXT NULL | `place_county_name` | Optional spatial summarization |
| captive_cultivated | BOOLEAN | `captive_cultivated` | Exclude if true |

Indexes:
```
```
Indexes (optional – can be omitted for the demo since latency is not a concern):
```
-- (Optional) CREATE INDEX idx_obs_taxon_month ON observations (taxon_id, observed_month);
-- (Optional) CREATE INDEX idx_obs_date ON observations (observed_date);
-- (Optional) CREATE INDEX idx_obs_lat_lon ON observations (latitude, longitude);
-- (Optional) CREATE INDEX idx_obs_geom ON observations USING GIST (geom);
```

### species
| Column | Type | Source / Logic |
|--------|------|----------------|
| taxon_id PK | BIGINT | `taxon_id` |
| scientific_name | TEXT | `scientific_name` |
| common_name | TEXT NULL | `common_name` |
| family | TEXT | `taxon_family_name` |
| subfamily | TEXT NULL | `taxon_subfamily_name` |
| tribe | TEXT NULL | `taxon_tribe_name` |
| genus | TEXT | `taxon_genus_name` |
| species_epithet | TEXT NULL | `taxon_species_name` |
| rank | TEXT | CASE WHEN species_epithet IS NOT NULL THEN 'species' ELSE 'genus' END |
| total_observations | INT | Computed after load |
| phenology_counts | INT[12] | Raw monthly counts (Jan..Dec) |
| phenology_normalized | NUMERIC[12] | Normalized curve (floats) |
| peak_month | SMALLINT | Argmax(normalized) |
| window_start | SMALLINT | Activity window start month |
| window_end | SMALLINT | Activity window end month |
| seasonality_index | NUMERIC | Concentration metric |
| insufficient_data | BOOLEAN | total_observations < MIN_OBS |
| peak_prominence | NUMERIC | max - second_max (optional) |

## 3. Column Mapping / Transform Rules

| Target | Source | Notes |
|--------|--------|-------|
| observation_id | id | Use as-is |
| taxon_id | taxon_id | Non-null required |
| observed_date | observed_on | Ensure parseable; skip if null |
| latitude/longitude | latitude/longitude | Round: `ROUND(value::numeric, 3)`; if coordinates_obscured then maybe 2 decimals |
| coordinates_obscured | coordinates_obscured or geoprivacy | Boolean OR logic |
| positional_accuracy | positional_accuracy / public_positional_accuracy | Prefer explicit positional_accuracy |
| observer_hash | user_id | `hashlib.sha256(SALT + str(user_id)).hexdigest()` (stable even if username changes) |
| county | place_county_name | Optional; leave NULL if blank |
| captive_cultivated | captive_cultivated | Exclude from phenology if true |
| rank | derived | Fallback if no explicit taxon_rank column |

Discard early: `uuid`, `observed_on_string`, `time_observed_at`, `time_zone`, `user_login`, `user_name`, `created_at`, `updated_at`, `image_url`, `sound_url`, `tag_list`, `description`, `oauth_application_id`, `private_*` fields, `positioning_*`, `place_guess`, `species_guess`, `iconic_taxon_name`, order/superfamily names (hardcoded domain knowledge), interaction fields. (Retain `user_id` only long enough to hash it; do not persist raw value if not needed elsewhere.)

## 4. Ingestion Pipeline Steps

High-level ETL process (can be a single Python script):

1. **Load CSV**
   - Stream with Python’s `csv` or pandas with `usecols` selecting only needed columns to reduce memory.
2. **Row Validation & Filtering**
   - Skip rows missing `taxon_id` or `observed_on`.
   - Drop rows where `captive_cultivated = true`.
3. **Insert into a staging table** (`observations_raw` or directly into `observations`). Use COPY for speed. After raw insert of numeric latitude/longitude, populate `geom` for rows with both coordinates:
   ```sql
   \copy observations(observation_id, taxon_id, observed_date, observed_year, observed_month, latitude, longitude, coordinates_obscured, positional_accuracy, quality_grade, license, observer_hash, county, captive_cultivated) FROM 'filtered.csv' CSV HEADER;
  UPDATE observations
    SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
   ```
4. **Populate species table**
   ```sql
   INSERT INTO species (taxon_id, scientific_name, common_name, family, subfamily, tribe, genus, species_epithet, rank)
   SELECT DISTINCT taxon_id, scientific_name, common_name, taxon_family_name, taxon_subfamily_name, taxon_tribe_name, taxon_genus_name, taxon_species_name,
          CASE WHEN taxon_species_name IS NOT NULL AND taxon_species_name <> '' THEN 'species' ELSE 'genus' END as rank
   FROM raw_import_species_view
   ON CONFLICT (taxon_id) DO NOTHING;
   ```
   *`raw_import_species_view` can be a staging view over the raw CSV load if you initially ingested more columns.*
7. **Compute Phenology Counts** (research grade only):
   ```sql
   WITH base AS (
     SELECT taxon_id, observed_month AS month, COUNT(*) AS c
     FROM observations
     WHERE quality_grade = 'research' AND (captive_cultivated IS NULL OR captive_cultivated = false)
     GROUP BY taxon_id, observed_month
   )
   SELECT taxon_id,
          ARRAY(SELECT COALESCE((SELECT c FROM base b2 WHERE b2.taxon_id = b.taxon_id AND b2.month = m),0)
                FROM generate_series(1,12) m) AS counts
   FROM base b
   GROUP BY taxon_id;
   ```
8. **Normalize & Derive Metrics** (Python recommended for clarity):
   - For each taxon counts array:
     - `total = sum(counts)`; if `total < MIN_OBS` → mark `insufficient_data` and still store raw counts.
     - `normalized = [c/total for c in counts]` (guard total>0).
     - Peak month = index of max normalized + 1.
     - Seasonality index (Herfindahl): `hhi = sum(v*v for v in normalized)`; `seasonality = (hhi - 1/12) / (1 - 1/12)`.
     - Activity window (coverage target ~0.8): greedy select months in descending normalized order until cumulative ≥ target; record min & max months; detect wrap if needed.
     - Coverage = sum(selected months).
   - Persist back:
     ```sql
     UPDATE species SET
       total_observations = %(total)s,
       phenology_counts = %(counts)s,
       phenology_normalized = %(normalized)s,
       peak_month = %(peak_month)s,
       window_start = %(window_start)s,
       window_end = %(window_end)s,
       seasonality_index = %(seasonality)s,
       insufficient_data = %(insufficient)s,
       peak_prominence = %(peak_prominence)s
     WHERE taxon_id = %(taxon_id)s;
     ```
9. **Skip Low-Latency Optimizations**
  For the demo, no precomputed species geometry is stored. Spatial filtering pulls distinct `taxon_id` directly from `observations` using the point radius query.

## 5. /bees/active Query Logic (Runtime)

Default spatial behavior: If the client omits `radius_km`, the API applies a default radius of 25 km (matching `api_design.md`).

Baseline algorithm:
1. Derive the unique months covered by `[start_date, end_date]`.
2. Determine effective radius: `effective_radius_km = radius_km_param OR 25`.
    Fetch candidate species IDs with at least one observation within the effective radius (uses raw observations, no centroid):
   ```sql
    SELECT DISTINCT taxon_id FROM observations
    WHERE geom IS NOT NULL
       AND ST_DWithin(
                geom,
                ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,
                :effective_radius_km * 1000
             );
   ```
    (If a future variant wants "unbounded" behavior, it can set a special flag to bypass this filter.)
3. For each candidate species row (load needed columns in one query), sum the relevant months of `phenology_normalized` → `activity_score`.
4. Filter on `min_activity`.
5. Sort by `activity_score` desc, then `total_observations` desc (tie-break), slice `limit`.

Edge Cases:
* Species with `insufficient_data = true` may be excluded or included with a low confidence flag (choose one—MVP can include).
* Empty result returns `data: []`.
* If spatial filter yields too few species (e.g., <5), you may optionally broaden radius (future enhancement; skip for MVP).

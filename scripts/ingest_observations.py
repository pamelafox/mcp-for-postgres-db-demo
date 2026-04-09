"""One-time ingestion script for bee observations CSV.

Moved from `fastapi_app.ingest_observations` to `scripts/ingest_observations.py` for clarity:
this is an operational/ETL script, not part of the FastAPI application package. Logic is
unchanged besides module path in usage docs.

Usage (inside dev container with DB running):
    python scripts/ingest_observations.py --csv data/observations.csv

Environment variables (or override with CLI flags):
    POSTGRES_HOST, POSTGRES_USERNAME, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT
"""

from __future__ import annotations

import csv
import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("ingest")

REQUIRED_COLUMNS = {
    "id",
    "taxon_id",
    "observed_on",
    "latitude",
    "longitude",
    "coordinates_obscured",
    "geoprivacy",
    "positional_accuracy",
    "public_positional_accuracy",
    "quality_grade",
    "license",
    "place_county_name",
    "captive_cultivated",
    "scientific_name",
    "common_name",
    "taxon_family_name",
    "taxon_subfamily_name",
    "taxon_tribe_name",
    "taxon_genus_name",
    "taxon_species_name",
    # taxon metadata (intentional duplicates in original list retained for parity)
    "scientific_name",
    "common_name",
    "taxon_family_name",
    "taxon_subfamily_name",
    "taxon_tribe_name",
    "taxon_genus_name",
    "taxon_species_name",
}

MIN_OBS = 5  # threshold to mark insufficient_data
PHENO_COVERAGE_TARGET = 0.8


@dataclass
class PhenologyMetrics:
    counts: list[int]
    normalized: list[float]
    total: int
    peak_month: int | None
    window_start: int | None
    window_end: int | None
    seasonality_index: float | None
    insufficient: bool
    peak_prominence: float | None


def month_activity_window(norm: Sequence[float], coverage: float) -> tuple[int, int]:
    indexed = list(enumerate(norm, start=1))
    ordered = sorted(indexed, key=lambda x: x[1], reverse=True)
    chosen: list[int] = []
    acc = 0.0
    for m, v in ordered:
        chosen.append(m)
        acc += v
        if acc >= coverage:
            break
    chosen_sorted = sorted(chosen)
    return chosen_sorted[0], chosen_sorted[-1]


def compute_metrics(counts: Sequence[int]) -> PhenologyMetrics:
    total = sum(counts)
    if total == 0:
        return PhenologyMetrics(list(counts), [0.0] * 12, 0, None, None, None, None, True, None)
    normalized = [c / total for c in counts]
    peak_val = max(normalized)
    peak_month = normalized.index(peak_val) + 1
    sorted_vals = sorted(normalized, reverse=True)
    peak_prominence = None
    if len(sorted_vals) > 1:
        peak_prominence = peak_val - sorted_vals[1]
    hhi = sum(v * v for v in normalized)
    seasonality = (hhi - 1 / 12) / (1 - 1 / 12) if total > 0 else None
    window_start, window_end = month_activity_window(normalized, PHENO_COVERAGE_TARGET)
    insufficient = total < MIN_OBS
    return PhenologyMetrics(
        counts=list(counts),
        normalized=normalized,
        total=total,
        peak_month=peak_month,
        window_start=window_start,
        window_end=window_end,
        seasonality_index=seasonality,
        insufficient=insufficient,
        peak_prominence=peak_prominence,
    )


def filter_and_transform_rows(csv_path: str, out_path: str) -> int:
    with open(csv_path, encoding="utf-8") as f_in, open(out_path, "w", newline="", encoding="utf-8") as f_out:
        reader = csv.DictReader(f_in)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")
        writer = csv.writer(f_out)
        writer.writerow(
            [
                "observation_id",
                "taxon_id",
                "observed_date",
                "observed_year",
                "observed_month",
                "latitude",
                "longitude",
                "coordinates_obscured",
                "positional_accuracy",
                "quality_grade",
                "license",
                "county",
                "captive_cultivated",
                "scientific_name",
                "common_name",
                "family",
                "subfamily",
                "tribe",
                "genus",
                "species_epithet",
                "rank",
            ]
        )
        kept = 0
        for row in reader:
            if not row.get("taxon_id") or not row.get("observed_on"):
                continue
            if row.get("captive_cultivated", "").lower() == "true":
                continue
            obs_raw = row["observed_on"].strip()
            try:
                obs_date = datetime.fromisoformat(obs_raw).date()
            except Exception:
                continue
            lat_f = lon_f = None
            lat = row.get("latitude")
            lon = row.get("longitude")
            if lat and lon:
                try:
                    lat_f = round(float(lat), 3)
                    lon_f = round(float(lon), 3)
                except ValueError:
                    pass
            coord_obscured = (row.get("coordinates_obscured", "").lower() == "true") or bool(row.get("geoprivacy"))
            pos_acc_raw = row.get("positional_accuracy") or row.get("public_positional_accuracy") or None
            try:
                pos_acc_int = int(pos_acc_raw) if pos_acc_raw is not None else None
            except ValueError:
                pos_acc_int = None
            scientific = row.get("scientific_name") or "unknown"
            common = row.get("common_name") or None
            family = row.get("taxon_family_name") or None
            subfamily = row.get("taxon_subfamily_name") or None
            tribe = row.get("taxon_tribe_name") or None
            genus = row.get("taxon_genus_name") or None
            species_ep = row.get("taxon_species_name") or None
            rank = None
            if species_ep and genus:
                rank = "species"
            elif genus and not species_ep:
                rank = "genus"
            elif tribe:
                rank = "tribe"
            elif subfamily:
                rank = "subfamily"
            elif family:
                rank = "family"
            writer.writerow(
                [
                    row["id"],
                    row["taxon_id"],
                    obs_date.isoformat(),
                    obs_date.year,
                    obs_date.month,
                    lat_f,
                    lon_f,
                    coord_obscured,
                    pos_acc_int,
                    row.get("quality_grade", ""),
                    row.get("license", ""),
                    row.get("place_county_name") or None,
                    row.get("captive_cultivated") or None,
                    scientific,
                    common,
                    family,
                    subfamily,
                    tribe,
                    genus,
                    species_ep,
                    rank,
                ]
            )
            kept += 1
    return kept


async def copy_observations(engine: AsyncEngine, temp_csv: str):
    columns = (
        "observation_id",
        "taxon_id",
        "observed_date",
        "observed_year",
        "observed_month",
        "latitude",
        "longitude",
        "coordinates_obscured",
        "positional_accuracy",
        "quality_grade",
        "license",
        "county",
        "captive_cultivated",
    )
    records: list[tuple] = []
    species_meta: dict[int, tuple[str, str | None, str | None, str | None, str | None, str | None, str | None]] = {}
    with open(temp_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:

            def f_or_none(v):
                if v in ("", None):
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None

            def i_or_none(v):
                if v in ("", None):
                    return None
                try:
                    return int(v)
                except ValueError:
                    return None

            def b_or_none(v):
                if v in (None, "", "None"):
                    return None
                return str(v).lower() == "true"

            obs_date = datetime.fromisoformat(row["observed_date"]).date()
            tid = int(row["taxon_id"])
            sci = row.get("scientific_name") or "unknown"
            common = row.get("common_name") or None
            family = row.get("family") or None
            subfamily = row.get("subfamily") or None
            tribe = row.get("tribe") or None
            genus = row.get("genus") or None
            species_ep = row.get("species_epithet") or None
            if tid not in species_meta or (species_meta[tid][0] == "unknown" and sci != "unknown"):
                species_meta[tid] = (sci, common, family, subfamily, tribe, genus, species_ep)
            records.append(
                (
                    int(row["observation_id"]),
                    tid,
                    obs_date,
                    int(row["observed_year"]),
                    int(row["observed_month"]),
                    f_or_none(row["latitude"]),
                    f_or_none(row["longitude"]),
                    b_or_none(row["coordinates_obscured"]),
                    i_or_none(row["positional_accuracy"]),
                    row.get("quality_grade"),
                    row.get("license"),
                    row.get("county"),
                    b_or_none(row.get("captive_cultivated")),
                )
            )
    async with engine.begin() as conn:
        for tid, (sci, common, family, subfamily, tribe, genus, species_ep) in species_meta.items():
            await conn.execute(
                text(
                    """
INSERT INTO species (
    taxon_id, scientific_name, common_name, family, subfamily, tribe, genus, species_epithet, rank
)
VALUES (
    :tid, :sci, :common, :family, :subfamily, :tribe, :genus, :species_ep, :rank
)
ON CONFLICT (taxon_id) DO UPDATE SET
    scientific_name = CASE
        WHEN species.scientific_name='unknown' AND EXCLUDED.scientific_name!='unknown'
            THEN EXCLUDED.scientific_name
        ELSE species.scientific_name
    END,
    common_name = COALESCE(species.common_name, EXCLUDED.common_name),
    family = COALESCE(species.family, EXCLUDED.family),
    subfamily = COALESCE(species.subfamily, EXCLUDED.subfamily),
    tribe = COALESCE(species.tribe, EXCLUDED.tribe),
    genus = COALESCE(species.genus, EXCLUDED.genus),
    species_epithet = COALESCE(species.species_epithet, EXCLUDED.species_epithet),
    rank = COALESCE(species.rank, EXCLUDED.rank)
                    """
                ),
                {
                    "tid": tid,
                    "sci": sci,
                    "common": common,
                    "family": family,
                    "subfamily": subfamily,
                    "tribe": tribe,
                    "genus": genus,
                    "species_ep": species_ep,
                    "rank": (
                        "species"
                        if species_ep and genus
                        else "genus"
                        if genus and not species_ep
                        else "tribe"
                        if tribe
                        else "subfamily"
                        if subfamily
                        else "family"
                        if family
                        else None
                    ),
                },
            )
        raw = await conn.get_raw_connection()
        driver_conn = raw.driver_connection
        await driver_conn.copy_records_to_table("observations", records=records, columns=list(columns))
        await conn.execute(
            text(
                "UPDATE observations SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography "
                "WHERE geom IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL"
            )
        )
    logger.info("Copied %d observations and upserted %d species", len(records), len(species_meta))


async def fetch_monthly_counts(engine: AsyncEngine, research_only: bool) -> dict[int, list[int]]:
    if research_only:
        base = (
            "SELECT taxon_id, observed_month, COUNT(*) AS c FROM observations "
            "WHERE quality_grade = 'research' AND (captive_cultivated IS NULL OR captive_cultivated = 'false') "
            "GROUP BY taxon_id, observed_month"
        )
    else:
        base = "SELECT taxon_id, observed_month, COUNT(*) AS c FROM observations GROUP BY taxon_id, observed_month"
    sql = text(base)
    data: dict[int, list[int]] = {}
    async with engine.connect() as conn:
        result = await conn.execute(sql)
        for taxon_id, month, c in result.fetchall():  # type: ignore
            arr = data.setdefault(taxon_id, [0] * 12)
            arr[int(month) - 1] = int(c)
    return data


async def persist_dual_metrics(
    engine: AsyncEngine,
    research_metrics: dict[int, PhenologyMetrics],
    all_metrics: dict[int, PhenologyMetrics],
):
    async with engine.begin() as conn:
        for taxon_id in set(research_metrics) | set(all_metrics):
            rm = research_metrics.get(taxon_id)
            am = all_metrics.get(taxon_id)
            await conn.execute(
                text(
                    "UPDATE species SET "
                    "total_observations=:r_total, "
                    "phenology_counts=:r_counts, "
                    "phenology_normalized=:r_norm, "
                    "peak_month=:r_peak, "
                    "window_start=:r_wstart, "
                    "window_end=:r_wend, "
                    "seasonality_index=:r_seasonality, "
                    "insufficient_data=:r_insufficient, "
                    "peak_prominence=:r_prom, "
                    "total_observations_all=:a_total, "
                    "phenology_counts_all=:a_counts, "
                    "phenology_normalized_all=:a_norm, "
                    "peak_month_all=:a_peak, "
                    "window_start_all=:a_wstart, "
                    "window_end_all=:a_wend, "
                    "seasonality_index_all=:a_seasonality, "
                    "insufficient_data_all=:a_insufficient, "
                    "peak_prominence_all=:a_prom "
                    "WHERE taxon_id=:taxon_id"
                ),
                {
                    "r_total": rm.total if rm else None,
                    "r_counts": rm.counts if rm else None,
                    "r_norm": rm.normalized if rm else None,
                    "r_peak": rm.peak_month if rm else None,
                    "r_wstart": rm.window_start if rm else None,
                    "r_wend": rm.window_end if rm else None,
                    "r_seasonality": rm.seasonality_index if rm else None,
                    "r_insufficient": rm.insufficient if rm else None,
                    "r_prom": rm.peak_prominence if rm else None,
                    "a_total": am.total if am else None,
                    "a_counts": am.counts if am else None,
                    "a_norm": am.normalized if am else None,
                    "a_peak": am.peak_month if am else None,
                    "a_wstart": am.window_start if am else None,
                    "a_wend": am.window_end if am else None,
                    "a_seasonality": am.seasonality_index if am else None,
                    "a_insufficient": am.insufficient if am else None,
                    "a_prom": am.peak_prominence if am else None,
                    "taxon_id": taxon_id,
                },
            )


async def run_ingestion(csv_path: str, engine: AsyncEngine):
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as tmp:
        tmp_path = tmp.name
    logger.info("Filtering & transforming rows -> %s", tmp_path)
    count = filter_and_transform_rows(csv_path, tmp_path)
    logger.info("Prepared %d rows for COPY", count)
    if count == 0:
        logger.warning("No rows to ingest; aborting.")
        return
    logger.info("COPYing into observations...")
    await copy_observations(engine, tmp_path)
    logger.info("Computing monthly counts (research-only)...")
    monthly_research = await fetch_monthly_counts(engine, research_only=True)
    research_metrics: dict[int, PhenologyMetrics] = {tid: compute_metrics(c) for tid, c in monthly_research.items()}
    logger.info("Computing monthly counts (all observations)...")
    monthly_all = await fetch_monthly_counts(engine, research_only=False)
    all_metrics: dict[int, PhenologyMetrics] = {tid: compute_metrics(c) for tid, c in monthly_all.items()}
    logger.info(
        "Persisting dual phenology metrics: %d research taxa, %d all-observation taxa",
        len(research_metrics),
        len(all_metrics),
    )
    await persist_dual_metrics(engine, research_metrics, all_metrics)
    logger.info("Ingestion complete: %d observations, %d species with dual metrics", count, len(research_metrics))


def build_engine_from_env() -> AsyncEngine:
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    load_dotenv()
    host = os.getenv("POSTGRES_HOST", "localhost")
    user = os.getenv("POSTGRES_USERNAME", "postgres")
    pwd = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("POSTGRES_DB", "postgres")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    url = f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"
    return create_async_engine(url, echo=False, pool_pre_ping=True)


async def _amain():
    import argparse

    parser = argparse.ArgumentParser(description="One-time bee observations ingestion")
    parser.add_argument("--csv", required=True, help="Path to source observations CSV")
    args = parser.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = build_engine_from_env()
    try:
        await run_ingestion(args.csv, engine)
    finally:
        await engine.dispose()


def main():
    import asyncio

    asyncio.run(_amain())


if __name__ == "__main__":
    main()

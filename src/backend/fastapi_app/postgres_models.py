"""SQLAlchemy ORM models for biodiversity observations & species phenology.

These reflect the minimal schema described in `ingestion.md`:
* `observations` - raw (filtered) iNaturalist observation records with a geography point.
* `species` - per‑taxon aggregated phenology metrics and precomputed arrays.

The models intentionally avoid premature indices / constraints beyond PK + obvious FKs.
Spatial queries rely on PostGIS via geoalchemy2's Geography type.
"""

from __future__ import annotations

from geoalchemy2 import Geography
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarative class."""


class Observation(Base):
    """Filtered bee observation row.

    Only the columns required for phenology + simple spatial presence queries are retained.
    Coordinates are stored twice: (latitude/longitude) for convenience and a Geography(Point,4326)
    column (`geom`) for efficient ST_DWithin radius filtering.
    """

    __tablename__ = "observations"

    observation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    taxon_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("species.taxon_id", ondelete="CASCADE"), index=True)

    observed_date: Mapped[str] = mapped_column(Date, nullable=False)
    observed_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    observed_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    geom: Mapped[object | None] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)

    coordinates_obscured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    positional_accuracy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_grade: Mapped[str] = mapped_column(String, nullable=False)
    license: Mapped[str | None] = mapped_column(String, nullable=True)
    county: Mapped[str | None] = mapped_column(String, nullable=True)
    captive_cultivated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Species(Base):
    """Per‑taxon phenology aggregates.

    Arrays:
    * phenology_counts: integer counts for months Jan..Dec (index 0 => Jan)
    * phenology_normalized: floating (numeric) normalized values summing to 1 (unless insufficient data)
    """

    __tablename__ = "species"

    taxon_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scientific_name: Mapped[str] = mapped_column(String, nullable=False)
    common_name: Mapped[str | None] = mapped_column(String, nullable=True)
    family: Mapped[str | None] = mapped_column(String, nullable=True)
    subfamily: Mapped[str | None] = mapped_column(String, nullable=True)
    tribe: Mapped[str | None] = mapped_column(String, nullable=True)
    genus: Mapped[str | None] = mapped_column(String, nullable=True)
    species_epithet: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[str | None] = mapped_column(String, nullable=True)

    # Research‑grade phenology (existing semantics maintained)
    total_observations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phenology_counts: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    phenology_normalized: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    peak_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    window_start: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    window_end: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    seasonality_index: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    insufficient_data: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    peak_prominence: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    # All‑observations phenology (includes non‑research quality) — Option 2 addition
    total_observations_all: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phenology_counts_all: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    phenology_normalized_all: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    peak_month_all: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    window_start_all: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    window_end_all: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    seasonality_index_all: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    insufficient_data_all: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    peak_prominence_all: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    # For ordering tie-break convenience; create an index if needed later.
    __table_args__ = ()


class Trip(Base):
    """User submitted bee watching / survey trip.

    Stored to demonstrate validation, normalization and retrieval patterns. Some
    fields (organizers, address lines, emails) are modeled as JSON/array blobs for
    simplicity; a real system might further normalize them.
    """

    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    event_slug: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    start_time: Mapped[str] = mapped_column(Date, nullable=False)
    end_time: Mapped[str] = mapped_column(Date, nullable=False)

    approx_latitude: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    approx_longitude: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    positional_accuracy_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSONB organizers: list[{original, normalized, has_diacritics, role}]
    organizers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Address lines stored as JSON array of strings
    address_lines: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    contact_emails: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    created_at: Mapped[str] = mapped_column(Date, nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("event_slug", name="uq_trips_event_slug"),)

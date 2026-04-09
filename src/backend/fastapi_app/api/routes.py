import re
from datetime import date, datetime, timedelta
from io import BytesIO

import fastapi
from fastapi import HTTPException, Query
from sqlalchemy import select, text

from fastapi_app.api.models import (
    ActiveBeeItem,
    ActiveBeesResponse,
    SpeciesSearchItem,
    SpeciesSearchResponse,
    TripCreate,
    TripListItem,
    TripListResponse,
    TripLocation,
    TripOrganizer,
    TripPublic,
    TripTimeWindow,
)
from fastapi_app.dependencies import DBSession
from fastapi_app.postgres_models import Species, Trip

router = fastapi.APIRouter()


# ---------------- Bee Activity Endpoints -----------------


def _parse_date(d: str) -> date:
    try:
        return datetime.fromisoformat(d).date()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid date '{d}': {e}")


@router.get("/bees/active", response_model=ActiveBeesResponse)
async def bees_active(
    database_session: DBSession,
    lat: float = Query(..., ge=-90, le=90, example=37.7749, description="Latitude of search center"),
    lon: float = Query(..., ge=-180, le=180, example=-122.4194, description="Longitude of search center"),
    start_date: str | None = Query(
        None,
        description="Start date (YYYY-MM-DD) inclusive; defaults to 30 days before today if omitted",
    ),
    end_date: str | None = Query(
        None,
        description="End date (YYYY-MM-DD) inclusive; defaults to today if omitted",
    ),
    radius_km: float = Query(25, gt=0, le=200, example=15, description="Search radius in kilometers"),
    limit: int = Query(25, gt=0, le=100, example=10, description="Maximum number of species"),
    min_activity: float = Query(
        0.05,
        ge=0,
        le=1,
        example=0.05,
        description="Minimum average activity score (absolute count threshold when absolute_activity=true)",
    ),
    sort: str = Query(
        "activity_desc",
        regex="^(activity_desc|activity_asc|peak_month|taxon_id)$",
        example="activity_desc",
        description="Sort order: activity_desc (default), activity_asc, peak_month, taxon_id",
    ),
    require_research_grade: bool = Query(
        False,
        example=False,
        description=(
            "If true, restrict activity computation to research-grade observations; "
            "otherwise use all observations phenology"
        ),
    ),
    absolute_activity: bool = Query(
        True,
        example=True,
        description=(
            "If true, activity_score is absolute window count (sum of observations in window months); "
            "if false, it is the normalized average (original behavior)."
        ),
    ),
    candidate_cap: int = Query(
        800,
        ge=50,
        le=5000,
        description="Hard cap on distinct candidate taxon IDs considered (defensive against huge spatial scans)",
    ),
) -> ActiveBeesResponse:
    """Return species with seasonal activity in the date window near location.

    Activity score: mean of species' normalized monthly phenology values for
    months intersecting the requested window (research-only phenology for now).
    """
    # Dynamic default window: last 30 days (inclusive)
    today = date.today()
    default_start = today - timedelta(days=30)
    s_date = _parse_date(start_date) if start_date else default_start
    e_date = _parse_date(end_date) if end_date else today
    if e_date < s_date:
        raise HTTPException(status_code=422, detail="end_date must be >= start_date")
    if (e_date - s_date).days > 31:
        raise HTTPException(status_code=422, detail="Max window is 31 days")

    # Identify calendar months touched (max 2 due to 31-day window constraint)
    months = {s_date.month, e_date.month}

    # Spatial + temporal candidate taxa (observations table ensures presence)
    # Use ST_DWithin (lon,lat) geography radius.
    radius_m = radius_km * 1000.0
    month_list = list(months)
    # Use a subquery to first gather distinct taxon_ids then cap
    stmt = text(
        """
        SELECT taxon_id FROM (
            SELECT DISTINCT o.taxon_id
            FROM observations o
            WHERE o.geom IS NOT NULL
              AND ST_DWithin(o.geom, ST_SetSRID(ST_MakePoint(:lon, :lat),4326)::geography, :radius)
              AND o.observed_month = ANY(:months)
            LIMIT :cap
        ) s
        """
    )
    result = await database_session.execute(
        stmt,
        {"lon": lon, "lat": lat, "radius": radius_m, "months": month_list, "cap": candidate_cap},
    )
    taxon_ids = [r[0] for r in result.fetchall()]
    if not taxon_ids:
        return ActiveBeesResponse(
            data=[],
            meta={
                "count": 0,
                "months": list(months),
                "lat": lat,
                "lon": lon,
                "radius_km": radius_km,
                "start_date": str(s_date),
                "end_date": str(e_date),
                "candidate_count": 0,
            },
        )

    species_rows = (await database_session.scalars(select(Species).where(Species.taxon_id.in_(taxon_ids)))).all()
    items: list[ActiveBeeItem] = []
    for sp in species_rows:
        counts = (sp.phenology_counts if require_research_grade else sp.phenology_counts_all) or []
        norm = (sp.phenology_normalized if require_research_grade else sp.phenology_normalized_all) or []
        if len(counts) != 12 or len(norm) != 12:
            continue
        if absolute_activity:
            window_val = sum(counts[m - 1] for m in months)
            # reinterpret min_activity as minimum absolute window count when absolute mode
            if window_val < min_activity:
                continue
            score = float(window_val)
        else:
            avg_norm = sum(norm[m - 1] for m in months) / len(months)
            if avg_norm < min_activity:
                continue
            score = float(avg_norm)
        items.append(
            ActiveBeeItem(
                taxon_id=sp.taxon_id,
                scientific_name=sp.scientific_name,
                common_name=sp.common_name,
                activity_score=round(score, 4),
                peak_month=(sp.peak_month if require_research_grade else sp.peak_month_all),
            )
        )
    # Sorting
    if sort == "activity_desc":
        items.sort(key=lambda x: x.activity_score, reverse=True)
    elif sort == "activity_asc":
        items.sort(key=lambda x: x.activity_score)
    elif sort == "peak_month":
        items.sort(key=lambda x: (x.peak_month or 13, -x.activity_score))
    elif sort == "taxon_id":
        items.sort(key=lambda x: x.taxon_id)
    items = items[:limit]
    return ActiveBeesResponse(
        data=items,
        meta={
            "count": len(items),
            "months": sorted(list(months)),
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "sort": sort,
            "require_research_grade": require_research_grade,
            "absolute_activity": absolute_activity,
            "start_date": str(s_date),
            "end_date": str(e_date),
            "defaulted_dates": (start_date is None or end_date is None),
            "candidate_count": len(taxon_ids),
            "candidate_cap": candidate_cap,
        },
    )


@router.get("/bees/search", response_model=SpeciesSearchResponse)
async def bees_search(
    database_session: DBSession,
    q: str = Query(..., min_length=2, description="Keyword(s) to search in scientific or common name"),
    limit: int = Query(25, gt=0, le=100, description="Maximum number of species to return"),
) -> SpeciesSearchResponse:
    """Full text search over species scientific and common names.

    Uses PostgreSQL plainto_tsquery with the simple configuration. Ranks results
    by ts_rank and falls back to alphabetical if ranks tie.
    """
    # Use a lightweight inline to_tsvector; no persisted tsvector column yet.
    sql = text(
        """
        SELECT
            s.taxon_id,
            s.scientific_name,
            s.common_name,
            s.rank,
            s.total_observations,
            s.total_observations_all,
            s.peak_month,
            s.peak_month_all,
            ts_rank(
              to_tsvector('simple', coalesce(s.scientific_name,'') || ' ' || coalesce(s.common_name,'')),
              plainto_tsquery('simple', :q)
            ) AS score
        FROM species s
      WHERE to_tsvector('simple', coalesce(s.scientific_name,'') || ' ' || coalesce(s.common_name,''))
          @@ plainto_tsquery('simple', :q)
        ORDER BY score DESC, s.scientific_name ASC
        LIMIT :limit
        """
    )
    result = await database_session.execute(sql, {"q": q, "limit": limit})
    rows = result.fetchall()
    items = [
        SpeciesSearchItem(
            taxon_id=r.taxon_id,
            scientific_name=r.scientific_name,
            common_name=r.common_name,
            rank=r.rank,
            total_observations=r.total_observations,
            total_observations_all=r.total_observations_all,
            peak_month=r.peak_month,
            peak_month_all=r.peak_month_all,
            score=float(r.score) if r.score is not None else None,
        )
        for r in rows
    ]
    return SpeciesSearchResponse(query=q, count=len(items), data=items)


# ---------------- Phenology Chart Endpoint (placeholder minimal SVG) -----------------


@router.get("/bees/phenology-chart/{taxon_id}")
async def bees_phenology_chart(
    taxon_id: int,
    database_session: DBSession,
    highlight_window: bool = Query(True, example=True, description="Highlight active window background"),
    width: int = Query(640, ge=320, le=1400, example=640, description="Image width in pixels"),
    height: int = Query(360, ge=240, le=1000, example=360, description="Image height in pixels"),
    require_research_grade: bool = Query(
        False,
        example=False,
        description=("If true, use research-grade phenology; otherwise all observations phenology"),
    ),
):
    """Return a PNG bar chart of monthly normalized activity for a taxon.

    The array used respects the require_research_grade flag. Bars show relative
    monthly activity (0-1 scaled). Peak month bar is highlighted. Optional
    active window shading if window metadata present.
    """
    sp = (await database_session.scalars(select(Species).where(Species.taxon_id == taxon_id))).first()
    if not sp:
        raise HTTPException(status_code=404, detail="Taxon not found")
    norm = (sp.phenology_normalized if require_research_grade else sp.phenology_normalized_all) or [0] * 12
    if len(norm) != 12:
        norm = [0] * 12
    counts = (sp.phenology_counts if require_research_grade else sp.phenology_counts_all) or [0] * 12
    if len(counts) != 12:
        counts = [0] * 12

    # Matplotlib rendering
    import matplotlib

    matplotlib.use("Agg")  # ensure headless backend
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    months = list(range(1, 13))
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    colors = []
    peak = sp.peak_month if require_research_grade else sp.peak_month_all
    for m in months:
        if peak and m == peak:
            colors.append("#2a72d4")
        else:
            colors.append("#5fa8ff")
    bar_values = [float(v) for v in norm]
    bars = ax.bar(months, bar_values, color=colors, edgecolor="#1b4e85")
    ax.set_xlabel("Month")
    ax.set_ylabel("Normalized Activity")
    ax.set_xticks(months)
    ax.set_xticklabels(month_labels, rotation=0)
    ax.set_ylim(0, max(0.01, max(bar_values + [0.0]) * 1.25))
    title_scope = "Research" if require_research_grade else "All obs"
    ax.set_title(f"{sp.scientific_name} ({title_scope})")

    window_start = sp.window_start if require_research_grade else sp.window_start_all
    window_end = sp.window_end if require_research_grade else sp.window_end_all
    if highlight_window and window_start and window_end:
        ax.axvspan(window_start - 0.5, window_end + 0.5, color="#ffe4b5", alpha=0.35)

    # Annotate bars with total observations (counts) for each month
    def _fmt_count(c: int) -> str:
        if c >= 1000000:
            return f"{c / 1_000_000:.1f}M"
        if c >= 1000:
            return f"{c / 1000:.1f}K"
        return str(c)

    for rect, c in zip(bars, counts):
        height = rect.get_height()
        ax.text(
            rect.get_x() + rect.get_width() / 2.0,
            height + (ax.get_ylim()[1] * 0.01),
            _fmt_count(int(c)),
            ha="center",
            va="bottom",
            fontsize=8,
            rotation=0,
            color="#123",
        )

    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    summary = (
        f"{sp.scientific_name} peak {peak}; window {window_start}-{window_end}"  # type: ignore
        if peak and window_start and window_end
        else f"{sp.scientific_name}"
    )
    return fastapi.Response(content=buf.getvalue(), media_type="image/png", headers={"X-Phenology-Summary": summary})


# ---------------- Trip Endpoints -----------------


_SCRIPT_RE = re.compile(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1>", re.I | re.S)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:300]


@router.post("/trips", response_model=TripPublic, status_code=201)
async def create_trip(database_session: DBSession, payload: TripCreate) -> TripPublic:
    # Basic validation
    try:
        st = datetime.fromisoformat(payload.start_time)
        et = datetime.fromisoformat(payload.end_time)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid timestamps: {e}")
    if et <= st:
        raise HTTPException(status_code=422, detail="end_time must be > start_time")
    if (et - st).total_seconds() / 3600.0 > 24:
        raise HTTPException(status_code=422, detail="Duration must be <= 24h")
    if not payload.organizers:
        raise HTTPException(status_code=422, detail="At least one organizer required")

    # Organizer normalization
    orgs: list[TripOrganizer] = []
    for o in payload.organizers:
        original = str(o.get("display_name", "")).strip()
        role = str(o.get("role", "")).strip() or None
        if not original:
            continue
        normalized = re.sub(r"[\u0300-\u036f]", "", original)
        has_diacritics = normalized != original
        orgs.append(
            TripOrganizer(
                original=original,
                normalized=normalized,
                has_diacritics=has_diacritics,
                role=role,
            )
        )
    if not orgs:
        raise HTTPException(status_code=422, detail="No valid organizers provided")

    slug = _slugify(payload.event_name)
    # Sanitize notes
    warnings: list[str] = []
    notes_raw = payload.notes or None
    notes_sanitized = None
    if notes_raw:
        sanitized = _SCRIPT_RE.sub("", notes_raw)
        if sanitized != notes_raw:
            warnings.append("notes: script/style tags removed")
        notes_sanitized = sanitized.strip()

    trip = Trip(
        event_name=payload.event_name,
        event_slug=slug,
        start_time=st.date(),
        end_time=et.date(),
        approx_latitude=payload.approx_latitude,
        approx_longitude=payload.approx_longitude,
        positional_accuracy_m=payload.positional_accuracy_m,
        organizers=[o.model_dump() for o in orgs],
        address_lines=[line.strip() for line in (payload.address_text or "").splitlines() if line.strip()] or None,
        country=payload.country_hint,
        contact_emails=payload.contact_emails or None,
        notes=notes_raw,
        notes_sanitized=notes_sanitized,
        warnings=warnings or None,
    )
    database_session.add(trip)
    await database_session.commit()
    await database_session.refresh(trip)
    duration_h = (et - st).total_seconds() / 3600.0
    return TripPublic(
        id=trip.id,
        event_slug=trip.event_slug,
        event_name=trip.event_name,
        time_window=TripTimeWindow(
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_hours=round(duration_h, 2),
        ),
        location=TripLocation(
            approx_latitude=trip.approx_latitude,
            approx_longitude=trip.approx_longitude,
            positional_accuracy_m=trip.positional_accuracy_m,
        ),
        organizers=orgs,
        address={
            "lines": trip.address_lines or [],
            "country": trip.country,
        }
        if trip.address_lines
        else None,
        notes_sanitized=trip.notes_sanitized,
        warnings=trip.warnings or [],
        created_at=str(trip.created_at),
    )


@router.get("/trips/{trip_id}", response_model=TripPublic)
async def get_trip(database_session: DBSession, trip_id: int) -> TripPublic:
    trip = (await database_session.scalars(select(Trip).where(Trip.id == trip_id))).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    duration_h = 24.0  # approximate (dates only stored)
    return TripPublic(
        id=trip.id,
        event_slug=trip.event_slug,
        event_name=trip.event_name,
        time_window=TripTimeWindow(
            start_time=str(trip.start_time),
            end_time=str(trip.end_time),
            duration_hours=duration_h,
        ),
        location=TripLocation(
            approx_latitude=trip.approx_latitude,
            approx_longitude=trip.approx_longitude,
            positional_accuracy_m=trip.positional_accuracy_m,
        ),
        organizers=[TripOrganizer(**o) for o in (trip.organizers or [])],
        address={
            "lines": trip.address_lines or [],
            "country": trip.country,
        }
        if trip.address_lines
        else None,
        notes_sanitized=trip.notes_sanitized,
        warnings=trip.warnings or [],
        created_at=str(trip.created_at),
    )


@router.get("/trips", response_model=TripListResponse)
async def list_trips(
    database_session: DBSession,
    since: str | None = Query(None, example="2025-04-01", description="Filter start_time >= this date (YYYY-MM-DD)"),
    before: str | None = Query(None, example="2025-05-01", description="Filter start_time < this date (YYYY-MM-DD)"),
) -> TripListResponse:
    stmt = select(Trip)
    if since:
        try:
            s = datetime.fromisoformat(since).date()
            stmt = stmt.where(Trip.start_time >= s)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid since date")
    if before:
        try:
            b = datetime.fromisoformat(before).date()
            stmt = stmt.where(Trip.start_time < b)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid before date")
    rows = (await database_session.scalars(stmt)).all()
    data = [TripListItem(id=r.id, event_name=r.event_name, start_time=str(r.start_time)) for r in rows]
    return TripListResponse(meta={"query": {"since": since, "before": before}, "count": len(data)}, data=data)

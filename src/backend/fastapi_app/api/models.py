from pydantic import BaseModel

# ---------------- Bee Activity Models -----------------


class ActiveBeeItem(BaseModel):
    taxon_id: int
    scientific_name: str
    common_name: str | None = None
    activity_score: float
    peak_month: int | None = None


class ActiveBeesResponse(BaseModel):
    data: list[ActiveBeeItem]
    meta: dict | None = None


# ---------------- Trip Models -----------------


class TripOrganizer(BaseModel):
    original: str
    normalized: str
    has_diacritics: bool
    role: str | None = None


class TripLocation(BaseModel):
    approx_latitude: float | None = None
    approx_longitude: float | None = None
    positional_accuracy_m: int | None = None


class TripTimeWindow(BaseModel):
    start_time: str
    end_time: str
    duration_hours: float | None = None


class TripCreate(BaseModel):
    event_name: str
    organizers: list[dict]
    address_text: str | None = None
    country_hint: str | None = None
    start_time: str
    end_time: str
    approx_latitude: float | None = None
    approx_longitude: float | None = None
    positional_accuracy_m: int | None = None
    contact_emails: list[str] | None = None
    notes: str | None = None


class TripPublic(BaseModel):
    id: int
    event_slug: str
    event_name: str
    time_window: TripTimeWindow
    location: TripLocation
    organizers: list[TripOrganizer]
    address: dict | None = None
    notes_sanitized: str | None = None
    warnings: list[str] | None = None
    created_at: str | None = None


class TripListItem(BaseModel):
    id: int
    event_name: str
    start_time: str


class TripListResponse(BaseModel):
    meta: dict
    data: list[TripListItem]


# --------------- Species Search Models ---------------


class SpeciesSearchItem(BaseModel):
    taxon_id: int
    scientific_name: str
    common_name: str | None = None
    rank: str | None = None
    total_observations: int | None = None
    total_observations_all: int | None = None
    peak_month: int | None = None
    peak_month_all: int | None = None
    score: float | None = None  # text search rank


class SpeciesSearchResponse(BaseModel):
    query: str
    count: int
    data: list[SpeciesSearchItem]

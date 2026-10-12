"""Pydantic request and response models."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.models import (
    EntityCategory,
    EntityStatus,
    EntityType,
    LocationKind,
    Role,
    ShipmentStatus,
    TelematicsProvider,
    VehicleStatus,
    VehicleType,
    VisitType,
)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    username: str
    full_name: str


class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    region_id: int | None
    full_name: str
    is_active: bool
    region_name: str | None = None


class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str


class EntityIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    type: EntityType
    category: EntityCategory
    address: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str = ""
    email: str = ""
    tax_number: str = ""
    current_balance: float = 0
    status: EntityStatus = EntityStatus.active
    region_id: int | None = None


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    type: EntityType | None = None
    category: EntityCategory | None = None
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = None
    email: str | None = None
    tax_number: str | None = None
    current_balance: float | None = None
    status: EntityStatus | None = None
    region_id: int | None = None


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: EntityType
    category: EntityCategory
    address: str
    latitude: float | None
    longitude: float | None
    phone: str
    email: str
    tax_number: str
    current_balance: float
    status: EntityStatus
    region_id: int | None
    region_name: str | None = None


class ImportResult(BaseModel):
    created: int
    warnings: list[str]


class GeocodeOut(BaseModel):
    latitude: float | None
    longitude: float | None
    warning: str | None = None


class ShipmentItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity: float = Field(gt=0)
    unit: str = "adet"


class VehicleIn(BaseModel):
    plate_number: str = Field(min_length=4, max_length=20)
    vehicle_type: VehicleType
    max_weight_kg: float = Field(ge=0, default=0)
    max_volume_m3: float = Field(ge=0, default=0)
    current_status: VehicleStatus = VehicleStatus.available
    region_id: int | None = None
    last_latitude: float | None = Field(default=None, ge=-90, le=90)
    last_longitude: float | None = Field(default=None, ge=-180, le=180)


class VehicleUpdate(BaseModel):
    plate_number: str | None = Field(default=None, min_length=4, max_length=20)
    vehicle_type: VehicleType | None = None
    max_weight_kg: float | None = Field(default=None, ge=0)
    max_volume_m3: float | None = Field(default=None, ge=0)
    current_status: VehicleStatus | None = None
    region_id: int | None = None
    last_latitude: float | None = Field(default=None, ge=-90, le=90)
    last_longitude: float | None = Field(default=None, ge=-180, le=180)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plate_number: str
    vehicle_type: VehicleType
    max_weight_kg: float
    max_volume_m3: float
    current_status: VehicleStatus
    region_id: int | None
    last_latitude: float | None
    last_longitude: float | None


class ShipmentIn(BaseModel):
    entity_id: int
    vehicle_id: int | None = None
    driver_id: int | None = None
    status: ShipmentStatus = ShipmentStatus.pending
    items_json: list[ShipmentItem] = Field(default_factory=list)
    delivery_date: date | None = None
    notes: str = ""


class ShipmentUpdate(BaseModel):
    vehicle_id: int | None = None
    driver_id: int | None = None
    status: ShipmentStatus | None = None
    items_json: list[ShipmentItem] | None = None
    delivery_date: date | None = None
    notes: str | None = None


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_id: int
    vehicle_id: int | None
    driver_id: int | None
    status: ShipmentStatus
    items_json: list
    delivery_date: date | None
    proof_of_delivery_img: str | None
    notes: str
    created_at: datetime
    entity_name: str | None = None
    entity_latitude: float | None = None
    entity_longitude: float | None = None
    vehicle_plate: str | None = None
    driver_name: str | None = None


class OptimizeStopIn(BaseModel):
    id: int
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = ""


class OptimizeIn(BaseModel):
    origin_lat: float = Field(ge=-90, le=90)
    origin_lng: float = Field(ge=-180, le=180)
    stops: list[OptimizeStopIn] = Field(min_length=1, max_length=100)


class OptimizeStopOut(BaseModel):
    id: int
    latitude: float
    longitude: float
    label: str
    leg_km: float


class OptimizeOut(BaseModel):
    stops: list[OptimizeStopOut]
    total_km: float


class VisitIn(BaseModel):
    entity_id: int
    user_id: int | None = None
    visit_type: VisitType
    notes: str = ""
    form_data_json: dict = Field(default_factory=dict)


class VisitFormIn(BaseModel):
    notes: str | None = None
    form_data_json: dict | None = None


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    entity_id: int
    visit_type: VisitType
    check_in_time: datetime | None
    check_out_time: datetime | None
    notes: str
    form_data_json: dict
    created_at: datetime
    user_name: str | None = None
    entity_name: str | None = None


class LastShipment(BaseModel):
    id: int
    status: ShipmentStatus
    delivery_date: date | None


class MapEntityPin(BaseModel):
    id: int
    name: str
    type: EntityType
    category: EntityCategory
    address: str
    latitude: float
    longitude: float
    phone: str
    current_balance: float
    status: EntityStatus
    region_id: int | None
    last_shipment: LastShipment | None = None


class MapVehiclePin(BaseModel):
    id: int
    plate_number: str
    vehicle_type: VehicleType
    current_status: VehicleStatus
    latitude: float
    longitude: float
    region_id: int | None
    tracked: bool = False
    moving: bool = False
    stale: bool = False
    speed_kmh: float | None = None
    last_seen_at: datetime | None = None


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    tax_number: str = Field(default="", max_length=32)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=160)
    address: str = ""


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    logo_path: str | None


class LocationIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: LocationKind
    address: str = ""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_default_depot: bool = False
    region_id: int | None = None


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    kind: LocationKind | None = None
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_default_depot: bool | None = None
    region_id: int | None = None


class LocationOut(LocationIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class IntegrationIn(BaseModel):
    provider: TelematicsProvider
    name: str = Field(min_length=2, max_length=120)
    poll_interval_min: int = Field(default=5, ge=1, le=1440)
    is_active: bool = True
    credentials: dict[str, str] = Field(default_factory=dict)


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    poll_interval_min: int | None = Field(default=None, ge=1, le=1440)
    is_active: bool | None = None
    credentials: dict[str, str] | None = None


class IntegrationOut(BaseModel):
    id: int
    provider: TelematicsProvider
    name: str
    poll_interval_min: int
    is_active: bool
    last_sync_at: datetime | None
    last_error: str | None
    vehicle_count: int
    configured_fields: list[str]


class IntegrationTestOut(BaseModel):
    ok: bool
    vehicle_count: int = 0
    message: str


class SyncOut(BaseModel):
    inserted: int
    matched_vehicles: int
    unmatched_ids: list[str]


class ExternalVehicleOut(BaseModel):
    external_id: str
    label: str
    plate: str | None = None
    linked_vehicle_id: int | None = None


class VehicleLinkIn(BaseModel):
    integration_id: int | None = None
    external_id: str | None = Field(default=None, max_length=80)


class LiveVehicleOut(BaseModel):
    id: int
    plate_number: str
    vehicle_type: VehicleType
    current_status: VehicleStatus
    integration_id: int | None
    integration_name: str | None
    external_id: str | None
    latitude: float | None
    longitude: float | None
    speed_kmh: float | None
    heading: float | None
    ignition_on: bool | None
    last_seen_at: datetime | None
    tracked: bool
    moving: bool
    stale: bool


class TrackPointOut(BaseModel):
    t: datetime
    lat: float
    lng: float
    speed: float


class TrackStopOut(BaseModel):
    index: int
    start: datetime
    end: datetime
    latitude: float
    longitude: float
    duration_min: float
    place_name: str | None
    place_kind: str | None
    planned: bool


class TrackSummaryOut(BaseModel):
    distance_km: float
    driving_min: float
    stopped_min: float
    first_move: datetime | None
    last_move: datetime | None
    max_speed_kmh: float


class TrackOut(BaseModel):
    vehicle_id: int
    plate_number: str
    date: date
    points: list[TrackPointOut]
    stops: list[TrackStopOut]
    summary: TrackSummaryOut
    missed_planned: list[str]


class ArchiveItemOut(BaseModel):
    id: int
    vehicle_id: int
    plate_number: str
    report_date: date
    distance_km: float
    created_at: datetime


class ReverseGeocodeOut(BaseModel):
    address: str | None
    warning: str | None = None


class RestoreOut(BaseModel):
    counts: dict[str, int]
    files: int
    backup_created_at: str | None
    warnings: list[str]


class PlaceOut(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float


class PlaceSearchOut(BaseModel):
    provider: str
    results: list[PlaceOut]
    warning: str | None = None


class MapData(BaseModel):
    entities: list[MapEntityPin]
    vehicles: list[MapVehiclePin]
    company_locations: list[LocationOut] = Field(default_factory=list)
    unlocated_count: int


class DashboardSummary(BaseModel):
    completed_visits_today: int
    shipments_on_route: int
    urgent_deliveries: int
    pending_shipments: int


class RoutePoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteIn(BaseModel):
    points: list[RoutePoint] = Field(min_length=2, max_length=50)


class RouteOut(BaseModel):
    coordinates: list[tuple[float, float]]
    distance_km: float
    duration_min: float


class MapConfig(BaseModel):
    app_name: str
    provider: str
    google_maps_api_key: str
    tile_url: str
    tile_attribution: str
    center_lat: float
    center_lng: float
    zoom: int
    depot_lat: float
    depot_lng: float
    depot_label: str
    vehicle_refresh_seconds: int

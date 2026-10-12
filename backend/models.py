"""Relational models for users, customers, fleet, shipments and field visits."""

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from backend.database import Base


class Role(str, enum.Enum):
    admin = "admin"
    logistics = "logistics"
    marketer = "marketer"
    driver = "driver"


class EntityType(str, enum.Enum):
    customer = "customer"
    supplier = "supplier"
    competitor = "competitor"
    other = "other"


class LocationKind(str, enum.Enum):
    headquarters = "Merkez"
    branch = "Şube"
    depot = "Depo"
    factory = "Fabrika"


class TelematicsProvider(str, enum.Enum):
    simulator = "simulator"
    arvento = "arvento"
    mobiliz = "mobiliz"


class EntityCategory(str, enum.Enum):
    vip = "VIP"
    active = "Aktif"
    potential = "Potansiyel"
    raw_material = "Hammadde Tedarikçisi"
    inactive = "Pasif"


class EntityStatus(str, enum.Enum):
    active = "aktif"
    inactive = "pasif"


class VehicleType(str, enum.Enum):
    van = "Kamyonet"
    truck = "Tır"
    minibus = "Minibüs"


class VehicleStatus(str, enum.Enum):
    available = "Musait"
    on_route = "Yolda"
    maintenance = "Bakımda"


class ShipmentStatus(str, enum.Enum):
    pending = "Bekliyor"
    on_route = "Yolda"
    delivered = "Teslim Edildi"
    cancelled = "İptal"


class VisitType(str, enum.Enum):
    marketing = "Pazarlama"
    collection = "Tahsilat"
    service = "Servis"


def _enum(enum_cls: type[enum.Enum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=40,
        values_callable=lambda obj: [item.value for item in obj],
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, returns aware UTC on every backend."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)

    users: Mapped[list["User"]] = relationship(back_populates="region")
    entities: Mapped[list["Entity"]] = relationship(back_populates="region")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="region")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role), index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    region: Mapped[Region | None] = relationship(back_populates="users")
    shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="driver",
        foreign_keys="Shipment.driver_id",
    )
    visits: Mapped[list["FieldVisit"]] = relationship(back_populates="user")


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[EntityType] = mapped_column(_enum(EntityType), index=True)
    category: Mapped[EntityCategory] = mapped_column(_enum(EntityCategory), index=True)
    address: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    tax_number: Mapped[str] = mapped_column(String(32), default="")
    current_balance: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[EntityStatus] = mapped_column(_enum(EntityStatus), default=EntityStatus.active, index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True, index=True)

    region: Mapped[Region | None] = relationship(back_populates="entities")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="entity")
    visits: Mapped[list["FieldVisit"]] = relationship(back_populates="entity")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(_enum(VehicleType))
    max_weight_kg: Mapped[float] = mapped_column(Float, default=0)
    max_volume_m3: Mapped[float] = mapped_column(Float, default=0)
    current_status: Mapped[VehicleStatus] = mapped_column(
        _enum(VehicleStatus),
        default=VehicleStatus.available,
        index=True,
    )
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("fleet_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    ignition_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    region: Mapped[Region | None] = relationship(back_populates="vehicles")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="vehicle")
    integration: Mapped["FleetIntegration | None"] = relationship(back_populates="vehicles")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[ShipmentStatus] = mapped_column(
        _enum(ShipmentStatus),
        default=ShipmentStatus.pending,
        index=True,
    )
    items_json: Mapped[list] = mapped_column(JSON, default=list)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    proof_of_delivery_img: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entity: Mapped[Entity] = relationship(back_populates="shipments")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="shipments")
    driver: Mapped[User | None] = relationship(back_populates="shipments", foreign_keys=[driver_id])


class FieldVisit(Base):
    __tablename__ = "field_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    visit_type: Mapped[VisitType] = mapped_column(_enum(VisitType))
    check_in_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    form_data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="visits")
    entity: Mapped[Entity] = relationship(back_populates="visits")


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Firmam")
    tax_number: Mapped[str] = mapped_column(String(32), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CompanyLocation(Base):
    __tablename__ = "company_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[LocationKind] = mapped_column(_enum(LocationKind))
    address: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_default_depot: Mapped[bool] = mapped_column(Boolean, default=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)

    region: Mapped[Region | None] = relationship()


class FleetIntegration(Base):
    __tablename__ = "fleet_integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[TelematicsProvider] = mapped_column(_enum(TelematicsProvider))
    name: Mapped[str] = mapped_column(String(120))
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="")
    poll_interval_min: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="integration")


class VehiclePosition(Base):
    __tablename__ = "vehicle_positions"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "recorded_at"),
        Index("ix_vehicle_positions_vehicle_time", "vehicle_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float] = mapped_column(Float, default=0)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    ignition_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class DailyRouteReport(Base):
    __tablename__ = "daily_route_reports"
    __table_args__ = (UniqueConstraint("vehicle_id", "report_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    file_pdf: Mapped[str] = mapped_column(String(255))
    file_xlsx: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    vehicle: Mapped[Vehicle] = relationship()

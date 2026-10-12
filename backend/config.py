"""Runtime settings loaded from the environment and an optional .env file."""

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Harita3000"
    database_url: str = "sqlite+aiosqlite:///./harita3000.db"
    jwt_secret: str = "dev-only-harita3000-change-this-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    auth_required: bool = False
    google_maps_api_key: str = ""
    map_provider: str = "auto"
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları'
    osrm_url: str = "https://router.project-osrm.org"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geocoder_user_agent: str = "Harita3000/1.0 (saha-operasyon)"
    map_center_lat: float = 37.7765
    map_center_lng: float = 29.0864
    map_zoom: int = 10
    depot_lat: float = 37.8000
    depot_lng: float = 29.0500
    depot_label: str = "Denizli Merkez Depo"
    upload_dir: str = "uploads"
    report_dir: str = "reports"
    cors_origins: str = "*"
    timezone: str = "Europe/Istanbul"
    integration_secret: str = "dev-only-harita3000-integration-secret"
    telematics_poller_enabled: bool = True
    scheduler_tick_seconds: int = 30
    vehicle_refresh_seconds: int = 60
    position_retention_days: int = 180
    daily_report_hour: int = 23
    daily_report_minute: int = 30

    @property
    def active_map_provider(self) -> str:
        if self.map_provider.strip().lower() == "osm":
            return "osm"
        return "google" if self.google_maps_api_key else "osm"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def resolved_database_url(self) -> str:
        prefix = "sqlite+aiosqlite:///./"
        if self.database_url.startswith(prefix):
            filename = self.database_url.removeprefix(prefix)
            path = (ROOT_DIR / filename).resolve().as_posix()
            return f"sqlite+aiosqlite:///{path}"
        return self.database_url

    @property
    def upload_path(self) -> Path:
        raw = Path(self.upload_dir)
        return raw if raw.is_absolute() else ROOT_DIR / raw

    @property
    def report_path(self) -> Path:
        raw = Path(self.report_dir)
        return raw if raw.is_absolute() else ROOT_DIR / raw

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

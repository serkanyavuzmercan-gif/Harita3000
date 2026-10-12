"""Distance helpers. PostGIS ST_Distance when the database is PostgreSQL."""

import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


async def distance_km(
    session: AsyncSession,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    if settings.is_postgres:
        try:
            result = await session.execute(
                text(
                    """
                    SELECT ST_Distance(
                        ST_SetSRID(ST_MakePoint(:lon1, :lat1), 4326)::geography,
                        ST_SetSRID(ST_MakePoint(:lon2, :lat2), 4326)::geography
                    ) / 1000.0
                    """
                ),
                {"lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2},
            )
            value = result.scalar_one()
            return float(value)
        except Exception:
            return haversine_km(lat1, lon1, lat2, lon2)
    return haversine_km(lat1, lon1, lat2, lon2)

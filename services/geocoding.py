"""Address to coordinate lookup. Google when a key is set, OpenStreetMap Nominatim otherwise."""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

from backend.config import settings
from services.http import SSL_CONTEXT

NOMINATIM_MIN_INTERVAL_S = 1.1
_nominatim_lock = asyncio.Lock()
_last_nominatim_call = 0.0

SEARCH_LIMIT = 6
SEARCH_BIAS_RADIUS_M = 50_000
SEARCH_BIAS_DEGREES = 1.5
SEARCH_CACHE_SIZE = 256
SEARCH_CACHE_TTL_S = 24 * 3600
_search_cache: OrderedDict[tuple, tuple[float, "SearchResult"]] = OrderedDict()


@dataclass
class GeocodeResult:
    latitude: float | None = None
    longitude: float | None = None
    warning: str | None = None


@dataclass
class ReverseResult:
    address: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class FoundPlace:
    name: str
    address: str
    latitude: float
    longitude: float


@dataclass
class SearchResult:
    provider: str
    places: list[FoundPlace] = field(default_factory=list)
    warning: str | None = None


async def search_places(query: str, near_lat: float, near_lng: float) -> SearchResult:
    """Free-text place search biased towards the given point (usually the map center)."""
    cleaned = " ".join(query.split())
    if len(cleaned) < 3:
        return SearchResult(provider="none", warning="En az 3 karakter yazın")
    provider = "google" if settings.google_maps_api_key else "osm"
    key = (provider, cleaned.casefold(), round(near_lat, 1), round(near_lng, 1))
    cached = _search_cache.get(key)
    if cached and time.monotonic() - cached[0] < SEARCH_CACHE_TTL_S:
        _search_cache.move_to_end(key)
        return cached[1]

    if provider == "google":
        result = await _google_text_search(cleaned, near_lat, near_lng)
        if not result.places:
            fallback = await _google_geocode_search(cleaned)
            if fallback.places:
                result = fallback
    else:
        result = await _nominatim_search(cleaned, near_lat, near_lng)

    if result.places:
        _search_cache[key] = (time.monotonic(), result)
        while len(_search_cache) > SEARCH_CACHE_SIZE:
            _search_cache.popitem(last=False)
    return result


async def _google_text_search(query: str, near_lat: float, near_lng: float) -> SearchResult:
    try:
        async with httpx.AsyncClient(timeout=12, verify=SSL_CONTEXT) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "X-Goog-Api-Key": settings.google_maps_api_key,
                    "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
                },
                json={
                    "textQuery": query,
                    "languageCode": "tr",
                    "regionCode": "TR",
                    "pageSize": SEARCH_LIMIT,
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": near_lat, "longitude": near_lng},
                            "radius": SEARCH_BIAS_RADIUS_M,
                        }
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        return SearchResult(provider="google", warning=f"Google Places araması reddedildi ({exc.response.status_code})")
    except httpx.HTTPError:
        return SearchResult(provider="google", warning="Google Places servisine ulaşılamadı")
    except ValueError:
        return SearchResult(provider="google", warning="Google Places yanıtı okunamadı")

    places: list[FoundPlace] = []
    for item in payload.get("places") or []:
        try:
            location = item["location"]
            name = (item.get("displayName") or {}).get("text") or item.get("formattedAddress") or ""
            places.append(
                FoundPlace(
                    name=name,
                    address=item.get("formattedAddress") or name,
                    latitude=float(location["latitude"]),
                    longitude=float(location["longitude"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not places:
        return SearchResult(provider="google", warning="Google'da sonuç bulunamadı")
    return SearchResult(provider="google", places=places)


async def _google_geocode_search(query: str) -> SearchResult:
    try:
        async with httpx.AsyncClient(timeout=12, verify=SSL_CONTEXT) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": settings.google_maps_api_key, "region": "tr", "language": "tr"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return SearchResult(provider="google", warning="Google Geocoding servisine ulaşılamadı")
    except ValueError:
        return SearchResult(provider="google", warning="Google Geocoding yanıtı okunamadı")

    places: list[FoundPlace] = []
    for item in (payload.get("results") or [])[:SEARCH_LIMIT]:
        try:
            location = item["geometry"]["location"]
            address = item.get("formatted_address") or query
            places.append(
                FoundPlace(
                    name=address.split(",")[0],
                    address=address,
                    latitude=float(location["lat"]),
                    longitude=float(location["lng"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not places:
        return SearchResult(provider="google", warning=f"Google sonucu: {payload.get('status') or 'bilinmiyor'}")
    return SearchResult(provider="google", places=places)


async def _nominatim_search(query: str, near_lat: float, near_lng: float) -> SearchResult:
    viewbox = ",".join(
        str(value)
        for value in (
            near_lng - SEARCH_BIAS_DEGREES,
            near_lat + SEARCH_BIAS_DEGREES,
            near_lng + SEARCH_BIAS_DEGREES,
            near_lat - SEARCH_BIAS_DEGREES,
        )
    )
    payload, error = await _nominatim_get(
        "search",
        {"q": query, "limit": SEARCH_LIMIT, "countrycodes": "tr", "viewbox": viewbox, "bounded": 0},
    )
    if error:
        return SearchResult(provider="osm", warning=error)
    places: list[FoundPlace] = []
    for item in payload if isinstance(payload, list) else []:
        try:
            address = str(item.get("display_name") or "")
            places.append(
                FoundPlace(
                    name=str(item.get("name") or address.split(",")[0]),
                    address=address,
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not places:
        return SearchResult(provider="osm", warning="OpenStreetMap'te sonuç bulunamadı")
    return SearchResult(provider="osm", places=places)


async def reverse_geocode(latitude: float, longitude: float) -> ReverseResult:
    if settings.google_maps_api_key:
        return await _google_reverse(latitude, longitude)
    payload, error = await _nominatim_get("reverse", {"lat": latitude, "lon": longitude, "zoom": 18})
    if error:
        return ReverseResult(warning=error)
    if not isinstance(payload, dict) or not payload.get("display_name"):
        return ReverseResult(warning="Bu nokta için adres bulunamadı")
    return ReverseResult(address=str(payload["display_name"]))


async def _google_reverse(latitude: float, longitude: float) -> ReverseResult:
    try:
        async with httpx.AsyncClient(timeout=12, verify=SSL_CONTEXT) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "latlng": f"{latitude},{longitude}",
                    "key": settings.google_maps_api_key,
                    "language": "tr",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return ReverseResult(warning="Google Geocoding servisine ulaşılamadı")
    except ValueError:
        return ReverseResult(warning="Google Geocoding yanıtı okunamadı")
    results = payload.get("results") or []
    if payload.get("status") != "OK" or not results:
        return ReverseResult(warning=f"Google Geocoding sonucu: {payload.get('status') or 'bilinmiyor'}")
    return ReverseResult(address=results[0].get("formatted_address"))


async def geocode_address(address: str) -> GeocodeResult:
    cleaned = address.strip()
    if not cleaned:
        return GeocodeResult(warning="Adres boş")
    if settings.google_maps_api_key:
        return await _google(cleaned)
    return await _nominatim(cleaned)


async def _google(address: str) -> GeocodeResult:
    try:
        async with httpx.AsyncClient(timeout=12, verify=SSL_CONTEXT) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": address, "key": settings.google_maps_api_key, "region": "tr"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return GeocodeResult(warning="Google Geocoding servisine ulaşılamadı")
    except ValueError:
        return GeocodeResult(warning="Google Geocoding yanıtı okunamadı")

    status = payload.get("status")
    if status != "OK" or not payload.get("results"):
        return GeocodeResult(warning=f"Google Geocoding sonucu: {status or 'bilinmiyor'}")
    try:
        location = payload["results"][0]["geometry"]["location"]
        return GeocodeResult(latitude=float(location["lat"]), longitude=float(location["lng"]))
    except (KeyError, IndexError, TypeError, ValueError):
        return GeocodeResult(warning="Google Geocoding koordinatı çözülemedi")


async def _nominatim_get(path: str, params: dict) -> tuple[object | None, str | None]:
    global _last_nominatim_call
    async with _nominatim_lock:
        wait = NOMINATIM_MIN_INTERVAL_S - (time.monotonic() - _last_nominatim_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(
                timeout=12,
                verify=SSL_CONTEXT,
                headers={"User-Agent": settings.geocoder_user_agent},
            ) as client:
                response = await client.get(
                    f"{settings.nominatim_url.rstrip('/')}/{path}",
                    params={**params, "format": "jsonv2", "accept-language": "tr"},
                )
                response.raise_for_status()
                return response.json(), None
        except httpx.HTTPError:
            return None, "OpenStreetMap adres servisine ulaşılamadı"
        except ValueError:
            return None, "OpenStreetMap adres yanıtı okunamadı"
        finally:
            _last_nominatim_call = time.monotonic()


async def _nominatim(address: str) -> GeocodeResult:
    payload, error = await _nominatim_get("search", {"q": address, "limit": 1, "countrycodes": "tr"})
    if error:
        return GeocodeResult(warning=error)
    if not isinstance(payload, list) or not payload:
        return GeocodeResult(warning="Adres OpenStreetMap'te bulunamadı")
    try:
        return GeocodeResult(latitude=float(payload[0]["lat"]), longitude=float(payload[0]["lon"]))
    except (KeyError, TypeError, ValueError):
        return GeocodeResult(warning="OpenStreetMap koordinatı çözülemedi")

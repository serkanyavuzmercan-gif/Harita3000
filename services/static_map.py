"""Renders a track over map tiles into a PNG for reports, without a browser."""

import asyncio
import io
import math
from collections import OrderedDict

import httpx
from PIL import Image, ImageDraw, ImageFont

from backend.config import ROOT_DIR, settings
from services.http import SSL_CONTEXT

TILE_SIZE = 256
MAX_ZOOM = 16
MIN_ZOOM = 3
TILE_CACHE_SIZE = 512
BACKGROUND = (232, 238, 233)
TRACK_COLOR = (31, 111, 91)
STOP_COLOR = (197, 106, 45)
START_COLOR = (22, 163, 74)
END_COLOR = (185, 28, 28)

FONT_PATH = ROOT_DIR / "backend" / "assets" / "fonts" / "DejaVuSans.ttf"

_tile_cache: "OrderedDict[tuple[int, int, int], bytes]" = OrderedDict()


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()


def _pixel(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2**zoom)
    x = (longitude + 180.0) / 360.0 * scale
    lat = max(min(latitude, 85.0511), -85.0511)
    siny = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    return x, y


def _fit_zoom(coords: list[tuple[float, float]], width: int, height: int, padding: int) -> int:
    if len(coords) < 2:
        return 14
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        pixels = [_pixel(lat, lng, zoom) for lat, lng in coords]
        span_x = max(x for x, _ in pixels) - min(x for x, _ in pixels)
        span_y = max(y for _, y in pixels) - min(y for _, y in pixels)
        if span_x <= width - 2 * padding and span_y <= height - 2 * padding:
            return zoom
    return MIN_ZOOM


def _tile_url(zoom: int, x: int, y: int) -> str:
    return settings.tile_url.replace("{s}", "a").format(z=zoom, x=x, y=y)


async def _fetch_tile(client: httpx.AsyncClient, gate: asyncio.Semaphore, zoom: int, x: int, y: int) -> bytes | None:
    key = (zoom, x, y)
    if key in _tile_cache:
        _tile_cache.move_to_end(key)
        return _tile_cache[key]
    async with gate:
        try:
            response = await client.get(_tile_url(zoom, x, y))
            response.raise_for_status()
        except httpx.HTTPError:
            return None
    _tile_cache[key] = response.content
    while len(_tile_cache) > TILE_CACHE_SIZE:
        _tile_cache.popitem(last=False)
    return response.content


async def render_track(
    track: list[tuple[float, float]],
    stops: list[tuple[float, float, str]] | None = None,
    width: int = 1000,
    height: int = 560,
    padding: int = 40,
    with_tiles: bool = True,
) -> bytes:
    stops = stops or []
    coords = list(track) + [(lat, lng) for lat, lng, _ in stops]
    if not coords:
        coords = [(settings.map_center_lat, settings.map_center_lng)]
    zoom = _fit_zoom(coords, width, height, padding)
    pixels = [_pixel(lat, lng, zoom) for lat, lng in coords]
    center_x = (max(x for x, _ in pixels) + min(x for x, _ in pixels)) / 2
    center_y = (max(y for _, y in pixels) + min(y for _, y in pixels)) / 2
    origin_x, origin_y = center_x - width / 2, center_y - height / 2

    canvas = Image.new("RGB", (width, height), BACKGROUND)
    if with_tiles:
        first_x, last_x = int(origin_x // TILE_SIZE), int((origin_x + width) // TILE_SIZE)
        first_y, last_y = int(origin_y // TILE_SIZE), int((origin_y + height) // TILE_SIZE)
        limit = 2**zoom
        wanted = [
            (x, y) for x in range(first_x, last_x + 1) for y in range(first_y, last_y + 1) if 0 <= y < limit
        ]
        gate = asyncio.Semaphore(4)
        async with httpx.AsyncClient(
            timeout=10,
            verify=SSL_CONTEXT,
            headers={"User-Agent": settings.geocoder_user_agent},
        ) as client:
            tiles = await asyncio.gather(*(_fetch_tile(client, gate, zoom, x % limit, y) for x, y in wanted))
        for (x, y), content in zip(wanted, tiles):
            if not content:
                continue
            try:
                with Image.open(io.BytesIO(content)) as tile:
                    canvas.paste(tile.convert("RGB"), (int(x * TILE_SIZE - origin_x), int(y * TILE_SIZE - origin_y)))
            except OSError:
                continue

    draw = ImageDraw.Draw(canvas)

    def local(lat: float, lng: float) -> tuple[float, float]:
        x, y = _pixel(lat, lng, zoom)
        return x - origin_x, y - origin_y

    if len(track) >= 2:
        draw.line([local(lat, lng) for lat, lng in track], fill=TRACK_COLOR, width=4, joint="curve")
    if track:
        for (lat, lng), color in ((track[0], START_COLOR), (track[-1], END_COLOR)):
            x, y = local(lat, lng)
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="white", width=2)
    font = _font(11)
    for lat, lng, label in stops:
        x, y = local(lat, lng)
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=STOP_COLOR, outline="white", width=2)
        draw.text((x, y), label, fill="white", font=font, anchor="mm")
    attribution = "© OpenStreetMap katkıcıları"
    text_width = draw.textlength(attribution, font=font)
    draw.rectangle((width - text_width - 12, height - 18, width, height), fill=(255, 255, 255))
    draw.text((width - text_width - 6, height - 16), attribution, fill=(60, 60, 60), font=font)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()

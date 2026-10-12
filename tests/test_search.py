import services.geocoding as geocoding
from tests.conftest import auth_headers

NOMINATIM_ROWS = [
    {"name": "Pamukkale Üniversitesi", "display_name": "Pamukkale Üniversitesi, Kınıklı, Pamukkale, Denizli, Türkiye",
     "lat": "37.7405", "lon": "29.1010"},
    {"display_name": "Pamukkale, Denizli, Türkiye", "lat": "37.9190", "lon": "29.1200"},
    {"display_name": "Bozuk kayıt", "lat": "yok", "lon": "29"},
]


def _fake_nominatim(calls):
    async def fake(path, params):
        calls.append((path, params))
        return NOMINATIM_ROWS, None

    return fake


async def test_osm_search_parses_results_biases_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(geocoding.settings, "google_maps_api_key", "")
    monkeypatch.setattr(geocoding, "_nominatim_get", _fake_nominatim(calls))
    geocoding._search_cache.clear()

    first = await geocoding.search_places("  pamukkale   üni ", 37.78, 29.09)
    second = await geocoding.search_places("Pamukkale üni", 37.78, 29.09)

    assert first.provider == "osm"
    assert [place.name for place in first.places] == ["Pamukkale Üniversitesi", "Pamukkale"]
    assert first.places[0].latitude == 37.7405
    assert second is first
    assert len(calls) == 1
    path, params = calls[0]
    assert path == "search" and params["q"] == "pamukkale üni"
    assert params["countrycodes"] == "tr" and params["bounded"] == 0
    assert params["viewbox"].split(",")[0] == str(29.09 - geocoding.SEARCH_BIAS_DEGREES)


async def test_short_query_does_not_call_any_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(geocoding, "_nominatim_get", _fake_nominatim(calls))
    result = await geocoding.search_places("ab", 37.78, 29.09)
    assert result.places == [] and result.warning and calls == []


async def test_google_falls_back_to_geocoding_when_places_fails(monkeypatch):
    monkeypatch.setattr(geocoding.settings, "google_maps_api_key", "test-key")
    geocoding._search_cache.clear()

    async def no_places(*_args):
        return geocoding.SearchResult(provider="google", warning="Places kapalı")

    async def geocode(query):
        return geocoding.SearchResult(
            provider="google", places=[geocoding.FoundPlace("Çamlık", "Çamlık, Denizli", 37.77, 29.08)]
        )

    monkeypatch.setattr(geocoding, "_google_text_search", no_places)
    monkeypatch.setattr(geocoding, "_google_geocode_search", geocode)
    result = await geocoding.search_places("Çamlık Denizli", 37.78, 29.09)
    assert result.provider == "google"
    assert [place.name for place in result.places] == ["Çamlık"]


async def test_search_endpoint_requires_login_and_returns_results(client, monkeypatch):
    monkeypatch.setattr(geocoding.settings, "google_maps_api_key", "")
    monkeypatch.setattr(geocoding, "_nominatim_get", _fake_nominatim([]))
    geocoding._search_cache.clear()

    anonymous = await client.get("/api/geocode/search?q=pamukkale")
    assert anonymous.status_code == 401

    headers = await auth_headers(client, "surucu")
    response = await client.get("/api/geocode/search?q=pamukkale&lat=37.78&lng=29.09", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "osm"
    assert body["results"][0] == {
        "name": "Pamukkale Üniversitesi",
        "address": "Pamukkale Üniversitesi, Kınıklı, Pamukkale, Denizli, Türkiye",
        "latitude": 37.7405,
        "longitude": 29.101,
    }

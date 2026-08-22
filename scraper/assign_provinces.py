"""
Voegt twee velden toe aan elke route in data/routes.geojson:
- "province": nodig voor de provincie-achievements ("eerste route in deze
  provincie", "elke provincie een keer gelopen"). Wandelnet zelf geeft dit
  niet per route mee, dus dit wordt afgeleid uit het beginpunt van de route
  (point-in-polygon tegen de officiele provinciegrenzen).
- "crosses_border": voor de grensoverschrijdende-route-achievement. Een
  route telt als grensoverschrijdend als een substantieel deel (>=25%) van
  zijn punten buiten alle provincies valt -- een lage drempel zou al snel
  valse positieven geven door vereenvoudigde kustlijnen in de brondata
  (duinroutes, dijken) die net buiten de gegeneraliseerde polygonen vallen
  zonder dat de route echt de grens over gaat.

Draai dit script na scrape_routes.py (heeft data/routes.geojson nodig).
Provinciegrenzen veranderen praktisch nooit, dus dit hoeft maar zelden
opnieuw.
"""
import json
from pathlib import Path

import requests

USER_AGENT = "ns-wandelroutes-kaart/0.1 (+https://github.com/Gizzje/ns-wandelroutes-kaart)"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROUTES_PATH = DATA_DIR / "routes.geojson"

# Vereenvoudigde provinciegrenzen (PDOK/CBS via cartomap.github.io), CC0-achtig
# vrij te gebruiken cartografisch materiaal.
PROVINCES_URL = "https://cartomap.github.io/nl/wgs84/provincie_2023.geojson"

BORDER_CROSSING_THRESHOLD = 0.25  # aandeel routepunten buiten NL


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray-casting test of punt (x, y) binnen een enkele polygon-ring ligt."""
    inside = False
    n = len(ring)
    x1, y1 = ring[0]
    for i in range(1, n + 1):
        x2, y2 = ring[i % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    else:
        return False

    if not rings:
        return False
    # Alleen de buitenring hoeft te matchen voor dit doel (provincies hebben
    # in deze vereenvoudigde dataset geen relevante "gaten").
    outer_rings = (
        [geometry["coordinates"][0]]
        if geometry["type"] == "Polygon"
        else [polygon[0] for polygon in geometry["coordinates"]]
    )
    return any(point_in_ring(lon, lat, ring) for ring in outer_rings)


def load_provinces() -> list[dict]:
    resp = requests.get(PROVINCES_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()["features"]


def find_province(lon: float, lat: float, provinces: list[dict]) -> str | None:
    for feature in provinces:
        if point_in_geometry(lon, lat, feature["geometry"]):
            return feature["properties"]["statnaam"]
    return None


def crosses_border(coords: list[list[float]], provinces: list[dict]) -> bool:
    outside = sum(
        1 for lon, lat in coords if not any(point_in_geometry(lon, lat, p["geometry"]) for p in provinces)
    )
    return (outside / len(coords)) >= BORDER_CROSSING_THRESHOLD if coords else False


def main():
    routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    provinces = load_provinces()

    matched = 0
    border_crossers = []
    for feature in routes["features"]:
        geometry = feature.get("geometry")
        if not geometry or geometry["type"] != "LineString" or not geometry["coordinates"]:
            feature["properties"]["province"] = None
            feature["properties"]["crosses_border"] = False
            continue

        coords = geometry["coordinates"]
        lon, lat = coords[0]
        province = find_province(lon, lat, provinces)
        feature["properties"]["province"] = province
        if province:
            matched += 1
        else:
            print(f"WAARSCHUWING: geen provincie gevonden voor {feature['properties']['name']}")

        crosses = crosses_border(coords, provinces)
        feature["properties"]["crosses_border"] = crosses
        if crosses:
            border_crossers.append(feature["properties"]["name"])

    ROUTES_PATH.write_text(json.dumps(routes, ensure_ascii=False), encoding="utf-8")
    print(f"Klaar: {matched}/{len(routes['features'])} routes aan een provincie gekoppeld.")
    print(f"Grensoverschrijdend: {', '.join(border_crossers) if border_crossers else '(geen)'}")


if __name__ == "__main__":
    main()

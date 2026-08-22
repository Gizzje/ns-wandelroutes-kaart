"""
Voegt twee velden toe aan elke route in data/routes.geojson:
- "province": nodig voor de provincie-achievements ("eerste route in deze
  provincie", "elke provincie een keer gelopen"). Wandelnet zelf geeft dit
  niet per route mee, dus dit wordt afgeleid uit de routegeometrie: elk punt
  van de route wordt tegen de officiele provinciegrenzen gelegd
  (point-in-polygon), en de provincie die onder de meeste punten voorkomt
  wint. Niet zomaar het beginpunt -- een route die met een enkel stukje net
  over de grens begint of eindigt (bijv. Krickenbecker Seen, dat in
  Kaldenkirchen, Duitsland start maar verder helemaal in Limburg loopt) moet
  wel aan zijn "echte" provincie gekoppeld blijven.
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
from collections import Counter
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


def analyze_route(coords: list[list[float]], provinces: list[dict]) -> tuple[str | None, bool]:
    """Geeft (provincie, gaat-de-grens-over) terug voor een routegeometrie.
    De provincie is de vaakst voorkomende onder de punten die wel in een
    provincie liggen (punten buiten Nederland tellen niet mee voor de
    provincie, wel voor de grensoverschrijding)."""
    if not coords:
        return None, False

    matches = [find_province(lon, lat, provinces) for lon, lat in coords]
    outside = sum(1 for m in matches if m is None)
    matched_counts = Counter(m for m in matches if m)
    province = matched_counts.most_common(1)[0][0] if matched_counts else None
    crosses = (outside / len(coords)) >= BORDER_CROSSING_THRESHOLD
    return province, crosses


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

        province, crosses = analyze_route(geometry["coordinates"], provinces)
        feature["properties"]["province"] = province
        feature["properties"]["crosses_border"] = crosses
        if province:
            matched += 1
        else:
            print(f"WAARSCHUWING: geen provincie gevonden voor {feature['properties']['name']}")
        if crosses:
            border_crossers.append(feature["properties"]["name"])

    ROUTES_PATH.write_text(json.dumps(routes, ensure_ascii=False), encoding="utf-8")
    print(f"Klaar: {matched}/{len(routes['features'])} routes aan een provincie gekoppeld.")
    print(f"Grensoverschrijdend: {', '.join(border_crossers) if border_crossers else '(geen)'}")


if __name__ == "__main__":
    main()

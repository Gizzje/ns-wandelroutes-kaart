"""
Haalt het Nederlandse hoofdspoornet op (via de OpenStreetMap Overpass API)
en alle NL-treinstations (via de open CC0-dataset van rijdendetreinen.nl),
en zet beide om naar GeoJSON voor op de kaart.

Draai dit script eenmalig / incidenteel opnieuw (het spoornet verandert
zelden) -- niet iets om bij elke paginabezoek te doen.
"""
import csv
import io
import json
from pathlib import Path

import requests

USER_AGENT = "ns-wandelroutes-kaart/0.1 (+https://github.com/Gizzje/ns-wandelroutes-kaart)"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="NL"][admin_level=2]->.nl;
(
  way["railway"="rail"]["usage"="main"](area.nl);
);
out geom;
"""
# CC0, zie https://www.rijdendetreinen.nl/en/open-data/stations
STATIONS_CSV_URL = "https://opendata.rijdendetreinen.nl/public/stations/stations-2023-09-nl.csv"

# Simplificatie-tolerantie in graden (~30m) -- houdt het bestand behapbaar
# voor de browser zonder de vorm van het net merkbaar aan te tasten.
SIMPLIFY_TOLERANCE = 0.0003

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def rdp(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker lijnvereenvoudiging."""
    if len(points) < 3:
        return points

    def perpendicular_distance(pt, start, end):
        if start == end:
            return ((pt[0] - start[0]) ** 2 + (pt[1] - start[1]) ** 2) ** 0.5
        num = abs(
            (end[1] - start[1]) * pt[0]
            - (end[0] - start[0]) * pt[1]
            + end[0] * start[1]
            - end[1] * start[0]
        )
        den = ((end[1] - start[1]) ** 2 + (end[0] - start[0]) ** 2) ** 0.5
        return num / den

    dmax, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            index, dmax = i, d

    if dmax > tolerance:
        left = rdp(points[: index + 1], tolerance)
        right = rdp(points[index:], tolerance)
        return left[:-1] + right
    return [points[0], points[-1]]


def fetch_rail_network() -> dict:
    resp = session.post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=180)
    resp.raise_for_status()
    data = resp.json()

    features = []
    for element in data["elements"]:
        geometry = element.get("geometry")
        if not geometry:
            continue
        coords = [(pt["lon"], pt["lat"]) for pt in geometry]
        coords = rdp(coords, SIMPLIFY_TOLERANCE)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
                "properties": {"ref": element.get("tags", {}).get("ref")},
            }
        )
    print(f"Spoornet: {len(features)} segmenten")
    return {"type": "FeatureCollection", "features": features}


def fetch_stations() -> dict:
    resp = session.get(STATIONS_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    features = []
    for row in reader:
        if row.get("country") != "NL":
            continue
        try:
            lat, lon = float(row["geo_lat"]), float(row["geo_lng"])
        except (KeyError, ValueError):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "code": row.get("code"),
                    # name_long spelt uit (bijv. "Utrecht Centraal" i.p.v.
                    # "Utrecht C.") -- duidelijker op de kaart, en nodig om
                    # routeeindpunten betrouwbaar tegen stationsnamen te
                    # kunnen matchen.
                    "name": row.get("name_long") or row.get("name_medium"),
                    "type": row.get("type"),
                },
            }
        )
    print(f"Stations: {len(features)}")
    return {"type": "FeatureCollection", "features": features}


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    rail = fetch_rail_network()
    (DATA_DIR / "rail_network.geojson").write_text(
        json.dumps(rail, ensure_ascii=False), encoding="utf-8"
    )

    stations = fetch_stations()
    (DATA_DIR / "stations.geojson").write_text(
        json.dumps(stations, ensure_ascii=False), encoding="utf-8"
    )

    print("Klaar.")


if __name__ == "__main__":
    main()

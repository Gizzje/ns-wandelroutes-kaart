"""
Haalt alle NS-wandelingen en OV-stappers op van wandelnet.nl en zet ze om
naar één GeoJSON-bestand (data/routes.geojson) met per route: naam,
start-/eindstation, lengte(s), terreinkenmerken en de routegeometrie (uit de
GPX van routemaker.nl).

Draai dit script opnieuw om de data te verversen (routes veranderen zelden,
maandelijks is ruim voldoende). Niet iets om bij elke paginabezoek te doen.
"""
import json
import re
import time
from pathlib import Path

import gpxpy
import requests
from bs4 import BeautifulSoup

USER_AGENT = "ns-wandelroutes-kaart/0.1 (+https://github.com/Gizzje/ns-wandelroutes-kaart)"
REQUEST_DELAY_SECONDS = 1.0
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "routes.geojson"

OVERVIEW_PAGES = [
    ("https://www.wandelnet.nl/ns-wandelingen", "ns-wandeling"),
    ("https://www.wandelnet.nl/ov-stappers", "ov-stapper"),
]

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def fetch(url: str) -> str:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp.text


def parse_lengths(text: str) -> list[float]:
    """'Lengte: 6.0 tot 17.4 KM' / '12 of 18 KM' / '9.8 KM' -> [6.0, 17.4] / [12, 18] / [9.8]"""
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    return [float(n.replace(",", ".")) for n in numbers]


def parse_overview(url: str, route_type: str) -> list[dict]:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    routes = []
    for card in soup.select("article.at-threeColumns__column"):
        title_el = card.select_one("h3.at-threeColumns__title")
        link_el = card.select_one("a.at-threeColumns__linkOverlay")
        text_el = card.select_one("p.at-threeColumns__text")
        if not title_el or not link_el:
            continue
        href = link_el.get("href", "")
        match = re.search(r"/wandelroute/(\d+)/", href)
        if not match:
            continue
        route_id = match.group(1)
        title = title_el.get_text(strip=True)
        name, _, stations = title.partition("|")
        name = name.strip()
        stations = stations.strip()
        # Meestal een gewoon koppelteken, een enkele route gebruikt een
        # en-dash (–) als scheidingsteken tussen start en eind.
        separator = " – " if " – " in stations else " - "
        start, _, end = stations.partition(separator)

        lengths = sorted(set(parse_lengths(text_el.get_text()))) if text_el else []
        available = bool(lengths)

        routes.append(
            {
                "id": route_id,
                "type": route_type,
                "name": name,
                "start_station": start.strip(),
                "end_station": end.strip() or start.strip(),
                "length_km_min": lengths[0] if lengths else None,
                "length_km_max": lengths[-1] if lengths else None,
                "length_km_options": lengths,
                "available": available,
                "detail_url": f"https://www.wandelnet.nl/wandelroute/{route_id}/",
            }
        )
    return routes


def parse_detail(route: dict) -> dict:
    html = fetch(route["detail_url"])
    soup = BeautifulSoup(html, "html.parser")

    tags: list[str] = []
    for prop in soup.select("li.routeInformation__property"):
        title_el = prop.select_one("span.routeInformation__title")
        if title_el and title_el.get_text(strip=True) == "Kenmerken:":
            info_text = prop.select_one("p.routeInformation__info").get_text()
            info_text = info_text.replace("Kenmerken:", "")
            tags = [t.strip() for t in info_text.split(",") if t.strip()]

    gpx_link = soup.select_one("a.routeAction__link--gpx")
    route["terrain_tags"] = tags
    route["gpx_url"] = gpx_link.get("href") if gpx_link else None
    return route


def fetch_geometry(gpx_url: str) -> list[list[float]] | None:
    resp = session.get(gpx_url, timeout=30)
    time.sleep(REQUEST_DELAY_SECONDS)
    if resp.status_code != 200 or not resp.text.strip():
        return None
    gpx = gpxpy.parse(resp.text)
    coords = []
    for track in gpx.tracks:
        for segment in track.segments:
            coords.extend([point.longitude, point.latitude] for point in segment.points)
    return coords or None


def main():
    all_routes: list[dict] = []
    for url, route_type in OVERVIEW_PAGES:
        routes = parse_overview(url, route_type)
        print(f"{url}: {len(routes)} routes gevonden")
        all_routes.extend(routes)

    features = []
    for i, route in enumerate(all_routes, start=1):
        print(f"[{i}/{len(all_routes)}] {route['name']} ({route['id']})")
        try:
            parse_detail(route)
        except requests.RequestException as e:
            print(f"  WAARSCHUWING: kon detailpagina niet ophalen: {e}")
            continue

        geometry = None
        if route["gpx_url"]:
            try:
                coords = fetch_geometry(route["gpx_url"])
                if coords:
                    geometry = {"type": "LineString", "coordinates": coords}
            except (requests.RequestException, Exception) as e:
                print(f"  WAARSCHUWING: kon GPX niet verwerken: {e}")

        if geometry is None:
            print("  WAARSCHUWING: geen routegeometrie, wordt overgeslagen op de kaart")

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "id": route["id"],
                    "type": route["type"],
                    "name": route["name"],
                    "start_station": route["start_station"],
                    "end_station": route["end_station"],
                    "length_km_min": route["length_km_min"],
                    "length_km_max": route["length_km_max"],
                    "length_km_options": route["length_km_options"],
                    "available": route["available"],
                    "terrain_tags": route["terrain_tags"],
                    "detail_url": route["detail_url"],
                },
            }
        )

    collection = {"type": "FeatureCollection", "features": features}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(f"\nKlaar: {len(features)} routes weggeschreven naar {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

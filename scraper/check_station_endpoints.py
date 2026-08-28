"""
Voegt een "ends_at_station"-veld toe aan elke route in data/routes.geojson:
of het eindpunt van de route overeenkomt met een echt treinstation. Nodig
voor de achievement "Dat is geen trein!" -- routes die ergens anders
eindigen (een dorpskern, een bushalte) dan bij een station.

Matcht op gedeelde kernwoorden i.p.v. exacte string, zodat bijv. "Amsterdam"
matcht met station "Amsterdam Centraal", "Wageningen" met "Ede-Wageningen",
en "Sloterdijk centrum" met "Amsterdam Sloterdijk" -- generieke woorden
("centrum", "centraal", ...) tellen niet mee, dus die matchen niet toevallig
met alles.

Draai dit na scrape_routes.py EN fetch_rail_network.py (heeft zowel
data/routes.geojson als data/stations.geojson nodig).
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROUTES_PATH = DATA_DIR / "routes.geojson"
STATIONS_PATH = DATA_DIR / "stations.geojson"

STOPWORDS = {"centrum", "centraal", "station", "cs", "c"}
MIN_WORD_LENGTH = 3


def normalize(name: str) -> str:
    name = name.lower()
    name = name.replace("’", "").replace("‘", "").replace("'", "")
    name = re.sub(r"[-–—_.]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def core_words(name: str) -> set[str]:
    return {w for w in normalize(name).split() if w not in STOPWORDS and len(w) >= MIN_WORD_LENGTH}


def matches_a_station(end_station: str, station_word_sets: list[set[str]]) -> bool:
    # "Oosterbeek of Wolfheze" / "Velp of Rheden" -> beide kanten proberen,
    # één treffer is genoeg.
    for candidate in re.split(r"\s+(?:of|or)\s+", end_station):
        candidate_words = core_words(candidate)
        if not candidate_words:
            continue
        for station_words in station_word_sets:
            if candidate_words & station_words:
                return True
    return False


def main():
    routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    station_word_sets = [core_words(f["properties"]["name"]) for f in stations["features"]]

    matched = 0
    not_at_station = []
    for feature in routes["features"]:
        end = feature["properties"]["end_station"]
        found = matches_a_station(end, station_word_sets)
        feature["properties"]["ends_at_station"] = found
        if found:
            matched += 1
        else:
            not_at_station.append(f"{feature['properties']['name']} ({end})")

    ROUTES_PATH.write_text(json.dumps(routes, ensure_ascii=False), encoding="utf-8")
    print(f"Klaar: {matched}/{len(routes['features'])} routes eindigen bij een (h)erkend station.")
    print("Eindigt niet bij een station:")
    for entry in not_at_station:
        print(f"  {entry}")


if __name__ == "__main__":
    main()

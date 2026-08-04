"""
Berekent statistieken (totale afstand, aantal routes, provincies) en
achievements uit iemands afgevinkte routes. Alles wordt on the fly herleid
uit routes.geojson + de afgevinkte route-ids -- er wordt niets apart
opgeslagen, dus nieuwe achievements hier toevoegen werkt met terugwerkende
kracht voor iedereen.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROUTES_PATH = DATA_DIR / "routes.geojson"

_routes_cache: dict[str, dict] | None = None


def _load_routes() -> dict[str, dict]:
    global _routes_cache
    if _routes_cache is None:
        data = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
        _routes_cache = {f["properties"]["id"]: f["properties"] for f in data["features"]}
    return _routes_cache


def _route_distance(props: dict, override_km: float | None) -> float:
    """Gebruikt de zelf opgegeven afstand als iemand die heeft ingevuld.
    Anders de langste lengtevariant van de route (bijv. bij '10,5 of 17,5 km'
    telt 17,5 km mee) -- zonder opgave is dat het meest motiverende
    uitgangspunt."""
    if override_km is not None:
        return override_km
    lo = props.get("length_km_min")
    hi = props.get("length_km_max")
    if lo is None:
        return 0.0
    return hi if hi is not None else lo


ACHIEVEMENTS = [
    {
        "id": "eerste_stap",
        "name": "Eerste stap",
        "description": "Vink je eerste route af.",
        "icon": "\U0001F45F",
        "check": lambda s: s["total_routes"] >= 1,
    },
    {
        "id": "vaste_wandelaar",
        "name": "Vaste wandelaar",
        "description": "5 routes afgevinkt.",
        "icon": "\U0001F392",
        "check": lambda s: s["total_routes"] >= 5,
    },
    {
        "id": "doorzetter",
        "name": "Doorzetter",
        "description": "10 routes afgevinkt.",
        "icon": "\U0001F3C5",
        "check": lambda s: s["total_routes"] >= 10,
    },
    {
        "id": "kwart_eeuw",
        "name": "Kwart eeuw",
        "description": "25 routes afgevinkt.",
        "icon": "\U0001F3C6",
        "check": lambda s: s["total_routes"] >= 25,
    },
    {
        "id": "ns_completionist",
        "name": "NS-completionist",
        "description": "Alle NS-wandelingen gelopen.",
        "icon": "\U0001F686",
        "check": lambda s: s["ns_total"] > 0 and s["ns_checked"] >= s["ns_total"],
    },
    {
        "id": "alles_gezien",
        "name": "Alles gezien",
        "description": "Elke route gelopen, inclusief OV-stappers.",
        "icon": "\U0001F30D",
        "check": lambda s: s["total_routes_available"] > 0
        and s["total_routes"] >= s["total_routes_available"],
    },
    {
        "id": "ov_avonturier",
        "name": "OV-avonturier",
        "description": "Een OV-stapper gelopen — niet meer onderhouden, dus een echte ontdekking.",
        "icon": "\U0001F9ED",
        "check": lambda s: s["ov_checked"] >= 1,
    },
    {
        "id": "tien_km",
        "name": "10 km",
        "description": "In totaal 10 km gewandeld.",
        "icon": "\U0001F6B6",
        "check": lambda s: s["total_distance_km"] >= 10,
    },
    {
        "id": "halve_marathon",
        "name": "Halve marathon",
        "description": "In totaal 21,1 km gewandeld.",
        "icon": "\U0001F3C3",
        "check": lambda s: s["total_distance_km"] >= 21.1,
    },
    {
        "id": "marathon",
        "name": "Marathon",
        "description": "In totaal 42,2 km gewandeld.",
        "icon": "\U0001F3C3",
        "check": lambda s: s["total_distance_km"] >= 42.2,
    },
    {
        "id": "eeuw_vol",
        "name": "Eeuw vol",
        "description": "In totaal 100 km gewandeld.",
        "icon": "\U0001F4AF",
        "check": lambda s: s["total_distance_km"] >= 100,
    },
    {
        "id": "op_stoom",
        "name": "Op stoom",
        "description": "In totaal 250 km gewandeld.",
        "icon": "\U0001F525",
        "check": lambda s: s["total_distance_km"] >= 250,
    },
    {
        "id": "vijfhonderd_club",
        "name": "500 km-club",
        "description": "In totaal 500 km gewandeld.",
        "icon": "\U00002B50",
        "check": lambda s: s["total_distance_km"] >= 500,
    },
    {
        "id": "provincie_hopper",
        "name": "Provincie-hopper",
        "description": "Routes gelopen in 3 verschillende provincies.",
        "icon": "\U0001F5FA",
        "check": lambda s: len(s["provinces_covered"]) >= 3,
    },
    {
        "id": "halverwege_nl",
        "name": "Halverwege Nederland",
        "description": "Routes gelopen in 6 verschillende provincies.",
        "icon": "\U0001F9ED",
        "check": lambda s: len(s["provinces_covered"]) >= 6,
    },
    {
        "id": "alle_provincies",
        "name": "Alle 12 provincies",
        "description": "In elke Nederlandse provincie een route gelopen.",
        "icon": "\U0001F451",
        "check": lambda s: len(s["provinces_covered"]) >= 12,
    },
    {
        "id": "boswandelaar",
        "name": "Boswandelaar",
        "description": "3 routes met het kenmerk ‘Bosrijk’ gelopen.",
        "icon": "\U0001F332",
        "check": lambda s: s["bosrijk_count"] >= 3,
    },
    {
        "id": "duinloper",
        "name": "Duinloper",
        "description": "Een route met het kenmerk ‘Kust en duinen’ gelopen.",
        "icon": "\U0001F3D6️",
        "check": lambda s: s["kust_en_duinen_count"] >= 1,
    },
    {
        "id": "van_hei_tot_heuvel",
        "name": "Van hei tot heuvel",
        "description": "Routes met 6 verschillende terreinkenmerken gelopen.",
        "icon": "\U0001F3A8",
        "check": lambda s: s["terrain_tags_covered"] >= 6,
    },
]


def compute_stats(checked_routes: dict[str, float | None]) -> dict:
    """checked_routes: {route_id: zelf opgegeven afstand in km, of None}."""
    routes = _load_routes()
    checked_ids = [rid for rid in checked_routes if rid in routes]
    checked = [routes[rid] for rid in checked_ids]

    total_distance = sum(_route_distance(routes[rid], checked_routes[rid]) for rid in checked_ids)
    provinces_covered = sorted({p["province"] for p in checked if p.get("province")})
    terrain_tags: set[str] = set()
    for p in checked:
        terrain_tags.update(p.get("terrain_tags", []))

    ns_total = sum(1 for p in routes.values() if p["type"] == "ns-wandeling")
    ns_checked = sum(1 for p in checked if p["type"] == "ns-wandeling")
    ov_checked = sum(1 for p in checked if p["type"] == "ov-stapper")

    stats = {
        "total_routes": len(checked),
        "total_routes_available": len(routes),
        "total_distance_km": round(total_distance, 1),
        "ns_checked": ns_checked,
        "ns_total": ns_total,
        "ov_checked": ov_checked,
        "provinces_covered": provinces_covered,
        "provinces_total": 12,
        "terrain_tags_covered": len(terrain_tags),
        "bosrijk_count": sum(1 for p in checked if "Bosrijk" in p.get("terrain_tags", [])),
        "kust_en_duinen_count": sum(
            1 for p in checked if "Kust en duinen" in p.get("terrain_tags", [])
        ),
    }

    achievements = [
        {
            "id": a["id"],
            "name": a["name"],
            "description": a["description"],
            "icon": a["icon"],
            "unlocked": bool(a["check"](stats)),
        }
        for a in ACHIEVEMENTS
    ]

    return {"stats": stats, "achievements": achievements}

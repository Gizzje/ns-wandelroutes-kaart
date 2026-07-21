const TERRAIN_ICONS = {
    "Bosrijk": "🌲",
    "Heide en zand(grond)": "🌾",
    "Kust en duinen": "🏖️",
    "Meren": "💧",
    "plassen en vennen": "💧",
    "Rivieren en kanalen": "🌊",
    "Heuvels": "⛰️",
    "Stedelijk": "🏙️",
    "Landgoederen": "🏰",
    "Cultureel erfgoed": "🏛️",
    "Boerenland": "🚜",
    "Vogels en wild": "🦆",
    "Gemarkeerd": "🚩",
};
const DEFAULT_ICON = "•";

const COLORS = {
    "ns-wandeling": "#2563eb",
    "ov-stapper": "#d97706",
};

const state = {
    user: null,
    checkedRouteIds: new Set(),
    routesLayer: null,
    routeLayersById: new Map(),
    filters: {
        minKm: 0,
        maxKm: 30,
        types: new Set(["ns-wandeling", "ov-stapper"]),
        terrainTags: new Set(),
        hideChecked: false,
    },
};

// tolerance = extra invisible click/tap radius (px) around every route line,
// on top of its drawn weight -- makes routes far easier to hit on a touch
// screen without changing how thick they look.
const map = L.map("map", { renderer: L.canvas({ tolerance: 12 }) }).setView([52.15, 5.3], 8);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers',
    maxZoom: 19,
}).addTo(map);

async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || `${resp.status} ${resp.statusText}`);
    }
    return resp.json();
}

function terrainIconsFor(tags) {
    return tags.map((t) => TERRAIN_ICONS[t] || DEFAULT_ICON).join(" ");
}

function lengthLabel(props) {
    const { length_km_min, length_km_max } = props;
    if (length_km_min == null) return "lengte onbekend";
    if (length_km_min === length_km_max) return `${length_km_min} km`;
    return `${length_km_min}–${length_km_max} km`;
}

function routeStyle(feature) {
    const props = feature.properties;
    const isChecked = state.checkedRouteIds.has(String(props.id));
    return {
        color: COLORS[props.type] || "#64748b",
        weight: 3,
        opacity: isChecked ? 0.3 : 0.8,
        dashArray: props.type === "ov-stapper" ? "6 4" : null,
    };
}

function highlightStyle() {
    return { weight: 6, opacity: 1 };
}

function routeMatchesFilters(props) {
    const f = state.filters;
    if (!f.types.has(props.type)) return false;

    const min = props.length_km_min ?? 0;
    const max = props.length_km_max ?? min;
    if (max < f.minKm || min > f.maxKm) return false;

    if (f.terrainTags.size > 0) {
        const hasMatch = props.terrain_tags.some((t) => f.terrainTags.has(t));
        if (!hasMatch) return false;
    }

    if (f.hideChecked && state.checkedRouteIds.has(String(props.id))) return false;

    return true;
}

function buildPopupContent(props) {
    const container = document.createElement("div");
    container.className = "route-popup";

    const title = document.createElement("h3");
    title.textContent = props.name;
    container.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${props.start_station} – ${props.end_station} · ${lengthLabel(props)}`;
    container.appendChild(meta);

    const tags = document.createElement("div");
    tags.className = "tags";
    tags.textContent = props.terrain_tags.map((t) => `${TERRAIN_ICONS[t] || DEFAULT_ICON} ${t}`).join("  ");
    container.appendChild(tags);

    const link = document.createElement("a");
    link.className = "wandelnet-link";
    link.href = props.detail_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Bekijk op Wandelnet →";
    container.appendChild(link);

    if (state.user) {
        const label = document.createElement("label");
        label.className = "checked-toggle";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = state.checkedRouteIds.has(String(props.id));
        checkbox.addEventListener("change", () => toggleChecked(props.id, checkbox.checked));
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(" Gelopen"));
        container.appendChild(label);
    } else {
        const hint = document.createElement("p");
        hint.className = "hint";
        hint.textContent = "Log in om deze route af te vinken.";
        container.appendChild(hint);
    }

    return container;
}

async function toggleChecked(routeId, checked) {
    try {
        await fetchJSON("/api/checked", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ route_id: String(routeId), checked }),
        });
        if (checked) state.checkedRouteIds.add(String(routeId));
        else state.checkedRouteIds.delete(String(routeId));
        applyFilters();
    } catch (err) {
        alert(`Kon niet opslaan: ${err.message}`);
    }
}

function applyFilters() {
    let visibleCount = 0;
    state.routeLayersById.forEach((layer) => {
        const props = layer.feature.properties;
        const visible = routeMatchesFilters(props);
        layer.setStyle(routeStyle(layer.feature));

        const isOnMap = state.routesLayer.hasLayer(layer);
        if (visible && !isOnMap) state.routesLayer.addLayer(layer);
        if (!visible && isOnMap) state.routesLayer.removeLayer(layer);
        if (visible) visibleCount++;
    });
    document.getElementById("route-count").textContent = visibleCount;
}

function buildTerrainFilterUI(allTags) {
    const container = document.getElementById("terrain-filters");
    container.innerHTML = "";
    [...allTags].sort().forEach((tag) => {
        const label = document.createElement("label");
        label.className = "checkbox";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = tag;
        checkbox.addEventListener("change", () => {
            if (checkbox.checked) state.filters.terrainTags.add(tag);
            else state.filters.terrainTags.delete(tag);
            applyFilters();
        });
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(` ${TERRAIN_ICONS[tag] || DEFAULT_ICON} ${tag}`));
        container.appendChild(label);
    });
}

function renderRoutes(routesGeoJSON) {
    const allTags = new Set();
    routesGeoJSON.features.forEach((f) => f.properties.terrain_tags.forEach((t) => allTags.add(t)));
    buildTerrainFilterUI(allTags);

    state.routesLayer = L.geoJSON(routesGeoJSON, {
        style: routeStyle,
        onEachFeature: (feature, layer) => {
            const props = feature.properties;
            layer.bindTooltip(`<div class="route-tooltip"><strong>${props.name}</strong><br>${lengthLabel(props)} · ${terrainIconsFor(props.terrain_tags)}</div>`, { sticky: true });
            layer.bindPopup(() => buildPopupContent(props));
            layer.on("mouseover", () => layer.setStyle(highlightStyle()).bringToFront());
            layer.on("mouseout", () => layer.setStyle(routeStyle(feature)));
            state.routeLayersById.set(String(props.id), layer);
        },
    }).addTo(map);

    applyFilters();
}

function renderRailNetwork(railGeoJSON) {
    L.geoJSON(railGeoJSON, {
        style: { color: "#94a3b8", weight: 1.3, opacity: 0.7 },
        interactive: false,
    }).addTo(map);
}

function renderStations(stationsGeoJSON) {
    L.geoJSON(stationsGeoJSON, {
        pointToLayer: (feature, latlng) =>
            L.circleMarker(latlng, {
                radius: 2.5,
                color: "#475569",
                fillColor: "#475569",
                fillOpacity: 1,
                weight: 1,
            }),
        onEachFeature: (feature, layer) => {
            layer.bindTooltip(feature.properties.name, { direction: "top" });
        },
    }).addTo(map);
}

function wireFilterControls() {
    document.getElementById("filter-min-km").addEventListener("input", (e) => {
        state.filters.minKm = parseFloat(e.target.value) || 0;
        applyFilters();
    });
    document.getElementById("filter-max-km").addEventListener("input", (e) => {
        state.filters.maxKm = parseFloat(e.target.value) || 30;
        applyFilters();
    });
    document.getElementById("filter-type-ns").addEventListener("change", (e) => {
        toggleSet(state.filters.types, "ns-wandeling", e.target.checked);
        applyFilters();
    });
    document.getElementById("filter-type-ov").addEventListener("change", (e) => {
        toggleSet(state.filters.types, "ov-stapper", e.target.checked);
        applyFilters();
    });
    document.getElementById("filter-hide-checked").addEventListener("change", (e) => {
        state.filters.hideChecked = e.target.checked;
        applyFilters();
    });
}

function toggleSet(set, value, on) {
    if (on) set.add(value);
    else set.delete(value);
}

function wireSidebarToggle() {
    const app = document.getElementById("app");
    const open = () => app.classList.add("sidebar-open");
    const close = () => app.classList.remove("sidebar-open");

    document.getElementById("sidebar-toggle").addEventListener("click", open);
    document.getElementById("sidebar-close").addEventListener("click", close);
    document.getElementById("sidebar-backdrop").addEventListener("click", close);
}

function setLoggedInUI(user) {
    state.user = user;
    document.getElementById("auth-form").hidden = !!user;
    document.getElementById("auth-logged-in").hidden = !user;
    if (user) document.getElementById("auth-user-name").textContent = user.name;
    document.getElementById("hide-checked-hint").hidden = !!user;
    document.getElementById("filter-hide-checked").disabled = !user;
}

async function loadCheckedRoutes() {
    if (!state.user) {
        state.checkedRouteIds = new Set();
        return;
    }
    const data = await fetchJSON("/api/checked");
    state.checkedRouteIds = new Set(data.route_ids.map(String));
}

async function refreshAfterAuthChange() {
    await loadCheckedRoutes();
    if (state.routesLayer) applyFilters();
}

function wireAuthControls() {
    const form = document.getElementById("auth-form");
    const errorEl = document.getElementById("auth-error");

    async function submitAuth(endpoint) {
        errorEl.textContent = "";
        const name = document.getElementById("auth-name").value.trim();
        const password = document.getElementById("auth-password").value;
        try {
            const data = await fetchJSON(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, password }),
            });
            setLoggedInUI(data.user);
            await refreshAfterAuthChange();
        } catch (err) {
            errorEl.textContent = err.message;
        }
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        submitAuth("/api/login");
    });
    document.getElementById("register-btn").addEventListener("click", () => submitAuth("/api/register"));

    document.getElementById("logout-btn").addEventListener("click", async () => {
        await fetchJSON("/api/logout", { method: "POST" });
        setLoggedInUI(null);
        await refreshAfterAuthChange();
    });
}

function renderStats(data) {
    const { stats, achievements } = data;

    document.getElementById("stat-distance").textContent = stats.total_distance_km;
    document.getElementById("stat-routes").textContent = stats.total_routes;
    document.getElementById("stat-provinces").textContent =
        `${stats.provinces_covered.length}/${stats.provinces_total}`;

    document.getElementById("stat-breakdown").textContent =
        `${stats.ns_checked}/${stats.ns_total} NS-wandelingen · ${stats.ov_checked} OV-stappers` +
        (stats.provinces_covered.length ? ` · ${stats.provinces_covered.join(", ")}` : "");

    const grid = document.getElementById("achievements-grid");
    grid.innerHTML = "";
    achievements.forEach((a) => {
        const tile = document.createElement("div");
        tile.className = "achievement" + (a.unlocked ? "" : " locked");

        const icon = document.createElement("div");
        icon.className = "achievement-icon";
        icon.textContent = a.icon;
        tile.appendChild(icon);

        const name = document.createElement("div");
        name.className = "achievement-name";
        name.textContent = a.name;
        tile.appendChild(name);

        const description = document.createElement("div");
        description.className = "achievement-description";
        description.textContent = a.description;
        tile.appendChild(description);

        grid.appendChild(tile);
    });
}

function wireStatsModal() {
    const backdrop = document.getElementById("stats-modal-backdrop");
    const modal = document.getElementById("stats-modal");

    const open = async () => {
        backdrop.hidden = false;
        modal.hidden = false;
        try {
            const data = await fetchJSON("/api/stats");
            renderStats(data);
        } catch (err) {
            alert(`Kon statistieken niet laden: ${err.message}`);
        }
    };
    const close = () => {
        backdrop.hidden = true;
        modal.hidden = true;
    };

    document.getElementById("stats-btn").addEventListener("click", open);
    document.getElementById("stats-modal-close").addEventListener("click", close);
    backdrop.addEventListener("click", close);
}

async function init() {
    wireFilterControls();
    wireAuthControls();
    wireSidebarToggle();
    wireStatsModal();

    const [routesGeoJSON, railGeoJSON, stationsGeoJSON, meData] = await Promise.all([
        fetchJSON("/api/data/routes.geojson"),
        fetchJSON("/api/data/rail_network.geojson"),
        fetchJSON("/api/data/stations.geojson"),
        fetchJSON("/api/me"),
    ]);

    setLoggedInUI(meData.user);
    await loadCheckedRoutes();

    renderRailNetwork(railGeoJSON);
    renderStations(stationsGeoJSON);
    renderRoutes(routesGeoJSON);
}

init().catch((err) => {
    console.error(err);
    alert(`Kon de kaart niet laden: ${err.message}`);
});

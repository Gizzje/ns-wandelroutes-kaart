# NS-wandelroutes kaart — setup & beheer

Een interactieve kaart van Nederland met het hoofdspoornet, alle NS-wandelingen
en OV-stappers van wandelnet.nl. Je kunt filteren op afstand en terrein, en
(na het aanmaken van een account) bijhouden welke routes je al gelopen hebt.
Vrienden/familie kunnen hun eigen account maken met hun eigen vinkjes.

## Hoe het in elkaar zit

```
scraper/            eenmalig/incidenteel te draaien scripts die de data ophalen
  scrape_routes.py     -> data/routes.geojson (alle routes + terreinkenmerken)
  fetch_rail_network.py -> data/rail_network.geojson + data/stations.geojson
backend/             de webserver (Flask)
  app.py               de website + API
  models.py            database (SQLite) voor accounts en afgevinkte routes
  app.db                wordt automatisch aangemaakt bij eerste keer starten
static/              de kaart zelf (HTML/CSS/JS, door de backend geserveerd)
data/                de opgehaalde GeoJSON-bestanden (niet in git, zelf genereren)
```

De data (routes, spoornet, stations) verandert zelden. Je hoeft de
scraper-scripts dus niet bij elke serverstart te draaien — alleen de eerste
keer, en daarna af en toe (bijv. eens per paar maanden) om te verversen.

## 1. Lokaal testen (op je eigen Windows-pc)

Eenmalig instellen:

```
cd "NS wandelroutes"
python -m venv .venv
.venv\Scripts\pip install -r scraper\requirements.txt -r backend\requirements.txt
```

Data ophalen (duurt een paar minuten, door bewust trage requests richting
wandelnet.nl — dit is netjes scrapen, geen server platleggen):

```
.venv\Scripts\python scraper\scrape_routes.py
.venv\Scripts\python scraper\fetch_rail_network.py
```

Server starten:

```
.venv\Scripts\python backend\app.py
```

Open http://localhost:5000 in je browser. Sluit de server af met Ctrl+C.

Wil je tijdens het lokaal testen de uitgebreide Flask-foutmeldingen zien?
Zet dan eerst `set FLASK_DEBUG=1` voordat je `app.py` start. Laat dit **uit**
op de LXC — de debugmodus van Flask staat toe dat bezoekers via een
foutpagina code op de server uitvoeren, dat wil je niet op iets dat naar
buiten open staat.

## 2. Data verversen

Draai de twee scraper-scripts opnieuw (stap hierboven) en herstart de
backend. Er is geen aparte "ververs"-knop in de website nodig.

## 3. Naar je LXC zetten

Dit gaat op dezelfde manier als de Cineville-notifier: bestanden via WinSCP
overzetten naar een map op de LXC, bijv. `/opt/ns-wandelroutes`.

Op de LXC (Debian/Ubuntu):

```
cd /opt/ns-wandelroutes
python3 -m venv .venv
.venv/bin/pip install -r scraper/requirements.txt -r backend/requirements-prod.txt
.venv/bin/python scraper/scrape_routes.py
.venv/bin/python scraper/fetch_rail_network.py
```

Kopieer `.env.example` naar `.env` en vul een echte geheime sleutel in
(gebruik **niet** de voorbeeldwaarde):

```
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
# plak de uitkomst achter SECRET_KEY= in .env
```

Draai de site met gunicorn (een echte productieserver, niet de
ontwikkelserver van Flask) als systemd-service, zodat hij blijft draaien en
automatisch herstart. Maak `/etc/systemd/system/ns-wandelroutes.service`:

```ini
[Unit]
Description=NS-wandelroutes kaart
After=network.target

[Service]
WorkingDirectory=/opt/ns-wandelroutes
EnvironmentFile=/opt/ns-wandelroutes/.env
ExecStart=/opt/ns-wandelroutes/.venv/bin/gunicorn --chdir backend --bind 127.0.0.1:5000 app:app
Restart=on-failure
User=www-data

[Install]
WantedBy=multi-user.target
```

Dan:

```
sudo systemctl daemon-reload
sudo systemctl enable --now ns-wandelroutes
sudo systemctl status ns-wandelroutes
```

De site draait nu lokaal op de LXC op poort 5000. Koppel dit aan dezelfde
manier waarop je al externe toegang tot je homelab hebt geregeld, zodat
vrienden en familie er ook bij kunnen.

De app gaat ervan uit dat hij achter precies **één** reverse proxy / tunnel
draait (voor het herkennen van het echte IP-adres van bezoekers, o.a. voor de
rate limit hieronder). Klopt dat niet met jouw opzet, pas dan de
`ProxyFix(...)`-regel bovenaan `backend/app.py` aan (zie de
[Werkzeug-documentatie](https://werkzeug.palletsprojects.com/en/latest/middleware/proxy_fix/)).

## 4. Beheer

- **Logs bekijken:** `journalctl -u ns-wandelroutes -f`
- **Herstarten na een wijziging:** `sudo systemctl restart ns-wandelroutes`
- **Data verversen:** scraper-scripts opnieuw draaien (zie stap 2) en daarna
  de service herstarten.
- **Accounts/vinkjes staan in** `backend/app.db` — dit bestand bevat dus
  echte gebruikersdata, neem het niet zomaar mee in een git-commit of back-up
  het apart als je dat belangrijk vindt.

## Beveiliging

Wat er al in zit:
- Wachtwoorden worden gehasht opgeslagen (nooit leesbaar), via werkzeug.
- Alle databasequeries zijn geparametriseerd (geen SQL-injectie mogelijk).
- Alle dynamische tekst in de pagina gaat via `textContent`, nooit via
  `innerHTML` (geen XSS mogelijk via naam, routegegevens e.d.).
- Bestandstoegang is beperkt tot een vaste whitelist (geen pad-trucjes naar
  andere bestanden op de server).
- De app weigert te starten zonder een echte `SECRET_KEY` (buiten
  `FLASK_DEBUG=1` om) — voorkomt dat sessies vervalst kunnen worden.
- Login/registratie zijn ge-rate-limit (max 8 pogingen per minuut per
  IP-adres) tegen wachtwoorden raden en het volspammen met nepaccounts.
- Sessiecookie staat op HttpOnly + SameSite=Lax + Secure (bij niet-debug),
  draait als niet-root (`www-data`) via systemd.

Bewuste, niet-opgeloste puntjes (lage impact, kun je later alsnog toevoegen):
- Geen CSRF-bescherming. Het enige wat daarmee te misbruiken valt is iemands
  eigen "gelopen"-vinkje aan/uit zetten via een kwaadaardige pagina die de
  bezoeker toevallig open heeft staan — vervelend, niet schadelijk.
- Registratie staat open voor iedereen die de link vindt, er is geen
  uitnodigingscode. Wil je dat wel, dan is een simpele "toegangscode"-check
  in `/api/register` een kleine toevoeging.

## Bekende beperkingen

- Van de 92 gevonden routes kon er 1 (Naardermeer) niet opgehaald worden
  omdat de detailpagina een 404 gaf op het moment van scrapen — mogelijk
  tijdelijk van de site gehaald. Draai de scraper later nog eens om te zien
  of hij terug is.
- Een klein aantal terreinkenmerken wordt soms in twee stukken geknipt
  (bijv. "Meren, plassen en vennen" wordt twee losse filter-tags) doordat
  wandelnet.nl deze kenmerken als kommagescheiden tekst aanbiedt zonder
  duidelijke scheiding. Cosmetisch, geen probleem voor het filteren.
- Het hoofdspoornet wordt eenmalig via OpenStreetMap opgehaald; bij een
  refresh kan dit rond de 20-40 seconden duren.

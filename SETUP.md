# Setup guide

Full walkthrough: local development, production deployment, and the
gotchas we hit while setting this up ourselves. No prior server experience
assumed.

## 1. Local development

```bash
git clone https://github.com/Gizzje/ns-wandelroutes-kaart.git
cd ns-wandelroutes-kaart
python3 -m venv .venv
./.venv/bin/pip install -r scraper/requirements.txt -r backend/requirements.txt
```

Fetch the data (takes a few minutes — the scraper deliberately rate-limits
itself to ~1 request/second, out of courtesy to wandelnet.nl):

```bash
./.venv/bin/python scraper/scrape_routes.py
./.venv/bin/python scraper/fetch_rail_network.py
./.venv/bin/python scraper/assign_provinces.py
```

This writes `data/routes.geojson`, `data/rail_network.geojson`, and
`data/stations.geojson`, and tags each route in `routes.geojson` with its
province (used for the province achievements). Route and rail data barely
changes, so you only need to re-run this occasionally (e.g. every few
months), not on every deploy. `assign_provinces.py` specifically only needs
re-running if you re-ran `scrape_routes.py` (it reads the routes file, it
doesn't fetch routes itself) — it's quick either way (a few seconds).

Start the app:

```bash
FLASK_DEBUG=1 ./.venv/bin/python backend/app.py
```

Open http://localhost:5000. `FLASK_DEBUG=1` enables Flask's debug mode
(verbose error pages, auto-reload) and lets the app start without a real
`SECRET_KEY` — **never** set this in production, see below.

## 2. Production deployment

### Get the code and data onto the server

```bash
git clone https://github.com/Gizzje/ns-wandelroutes-kaart.git /opt/ns-wandelroutes
cd /opt/ns-wandelroutes
python3 -m venv .venv
./.venv/bin/pip install -r scraper/requirements.txt -r backend/requirements-prod.txt
./.venv/bin/python scraper/scrape_routes.py
./.venv/bin/python scraper/fetch_rail_network.py
./.venv/bin/python scraper/assign_provinces.py
```

(No git on the server? Copy the repo folder over some other way, e.g.
`scp`/`rsync`/WinSCP — just make sure `data/` ends up populated one way or
another, either by copying already-generated `.geojson` files or by running
the scrapers on the server itself.)

### Secret key

The app refuses to start outside of `FLASK_DEBUG=1` without a real
`SECRET_KEY` — without one, a visitor could forge session cookies and
impersonate other users. Generate one and put it in `.env`:

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
# paste the output after SECRET_KEY= in .env
```

### Run it with gunicorn as a systemd service

Don't use `backend/app.py`'s built-in server in production — it's a
development server. Use gunicorn (already in `requirements-prod.txt`) via
systemd, so it survives reboots and restarts on crash.

Create `/etc/systemd/system/ns-wandelroutes.service`:

```ini
[Unit]
Description=NS-wandelroutes kaart
After=network.target

[Service]
WorkingDirectory=/opt/ns-wandelroutes
EnvironmentFile=/opt/ns-wandelroutes/.env
ExecStart=/opt/ns-wandelroutes/.venv/bin/gunicorn --chdir backend --bind 0.0.0.0:5000 app:app
Restart=on-failure
User=www-data

[Install]
WantedBy=multi-user.target
```

**Bind address matters:** use `0.0.0.0:5000` if your reverse proxy runs on
a *different* machine/container and connects over the network. Use
`127.0.0.1:5000` if it runs on the same host — that way port 5000 isn't
reachable at all from your LAN, only from the reverse proxy sitting next to
it. Port 5000 itself should never be reachable directly from the internet
either way; that's what the reverse proxy is for.

The service runs as `www-data`, not root. Make sure that user can write to
the project directory (it needs to create `backend/app.db` on first run):

```bash
chown -R www-data:www-data /opt/ns-wandelroutes
```

Enable and start it:

```bash
systemctl daemon-reload
systemctl enable --now ns-wandelroutes
systemctl status ns-wandelroutes
```

(No `sudo` on your system, e.g. a minimal LXC container? Just drop the
`sudo` prefix if you're already root — check your prompt.)

### Put it behind a reverse proxy

Point your reverse proxy (Caddy, nginx, Nginx Proxy Manager, Traefik, ...)
at `<server-ip>:5000` and let it handle the public domain name and HTTPS
certificate. The app assumes exactly **one** reverse proxy hop in front of
it (see `ProxyFix(...)` near the top of `backend/app.py`) so it can tell
real visitor IPs apart from the proxy's own — adjust that line if your
setup differs.

## Security

What's already handled:

- Passwords are hashed (never stored in plain text), via werkzeug.
- All database queries are parameterized (no SQL injection).
- All dynamic content in the page goes through `textContent`, never
  `innerHTML` (no XSS via names, route data, etc.).
- File access is limited to an explicit whitelist (no path traversal to
  other files on the server).
- The app refuses to start without a real `SECRET_KEY` outside of
  `FLASK_DEBUG=1`.
- Login/registration are rate-limited (max 8 attempts/minute/IP) against
  password guessing and mass fake-account creation.
- Session cookie is HttpOnly + SameSite=Lax + Secure (outside debug mode).
- Runs as a non-root user via systemd.

Known, deliberately unaddressed gaps (low impact — see the README's
Limitations section): no CSRF protection, and self-registration has no
invite gate.

## Troubleshooting

Real problems hit while deploying this, in case they save you some time:

- **`Permission denied` in the systemd logs, service still shows
  `active (running)`** — `www-data` can't write to the project directory
  (usually to create `backend/app.db`). Run
  `chown -R www-data:www-data /opt/ns-wandelroutes` and restart.
- **502 Bad Gateway from your reverse proxy** — almost always a bind
  address mismatch. If your proxy runs on a different host/container than
  the app, gunicorn must bind to `0.0.0.0:5000`, not `127.0.0.1:5000` (see
  above) — the latter only accepts connections from the same machine.
- **Changed the systemd unit file but nothing changed after
  `systemctl enable --now`** — that command only *starts* a service that
  isn't running yet; on an already-running service it's a no-op. Use
  `systemctl restart ns-wandelroutes` to actually pick up config changes.
  Check `systemctl status` for a fresh PID/start time to confirm.
- **`gunicorn[...]: [ERROR] Control server error: [Errno 13] Permission
  denied: '/var/www'`** in the logs — harmless. It's an internal gunicorn
  startup probe unrelated to this app's own configuration (nothing here
  references `/var/www`); it doesn't affect serving requests. Confirm the
  app actually works with `curl -i http://127.0.0.1:5000` (or
  `python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:5000').status)"`
  if `curl` isn't installed) rather than worrying about this line.
- **`fetch_rail_network.py` fails with `504 Gateway Timeout` for
  `overpass-api.de`** — the free public Overpass API is shared and
  sometimes overloaded, especially for a query this size (~18MB
  uncompressed). Just retry later; it's not a bug. Since the rail network
  and stations barely change, you often don't even need to re-run this —
  reuse a previously generated `data/rail_network.geojson` /
  `data/stations.geojson` if you have one.
- **SSL certificate request fails in your reverse proxy with a vague
  "Internal Error"** — most likely the domain's DNS record doesn't exist
  or hasn't propagated yet (Let's Encrypt needs to reach the domain
  publicly to verify it), or you've hit Let's Encrypt's rate limit after a
  few failed attempts (5 failures/hour/hostname). Check the proxy's own
  container logs for the real underlying error rather than the generic
  toast message.

## Updating

Static files (`static/*`) are re-read on every request — no restart
needed, just re-deploy them and reload the page. Python code changes
(`backend/*.py`) need a service restart:

```bash
systemctl restart ns-wandelroutes
```

To refresh the route/rail/station/province data, re-run the scraper scripts
(see above) and reload — no restart needed for that either, since it's
served as static files too.

**Updating an existing deployment to a version that added the stats
dashboard:** you need both a code update (`git pull` + `systemctl restart`,
since `backend/achievements.py` and the new `/api/stats` endpoint are
Python code) and one data update — run `scraper/assign_provinces.py` once
to add province tags to your existing `data/routes.geojson` (no need to
re-run the other scrapers, your existing route/rail/station data is still
fine).

**Updating to a version that added picking which length variant you
walked:** code update as usual (`git pull` + `systemctl restart`).
`backend/models.py` adds a `distance_km` column to the `checked_routes`
table automatically the next time the app starts — existing accounts and
checked-off routes are untouched (they just default to "unspecified", same
as the old always-assume-longest behavior, until someone picks a specific
distance). Re-run `scraper/scrape_routes.py` to backfill the length
variants themselves into `data/routes.geojson` — routes scraped before this
version only have the shortest/longest length stored, not the full list, so
the picker won't show every option until you do.

**Updating to a version that added the "Grenzeloos" (border-crossing)
achievement:** code update as usual. Re-run `scraper/assign_provinces.py`
once to backfill the `crosses_border` field into `data/routes.geojson` (no
need to re-run `scrape_routes.py` for this one).

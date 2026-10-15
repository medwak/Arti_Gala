# Arti Gala

Arti Gala tracks sub-Saharan African artifacts (paintings, masks, sculpture, ornaments, textiles and
more) held by national museums, other museums and private collections. For each object it records:

- **where it is now**: the current holder (national museum, public museum, private collection, dealer…)
- **where it has been**: an ordered provenance timeline (collected, looted, sold, inherited, loaned, restituted…)
- **its origin and history**: culture, country, sub-region, date, materials and the full provenance narrative
- **auctions and prices**: lots with estimates, hammer price and price with premium, plus stats per currency
- **cases**: restitution claims, repatriations, lawsuits, theft investigations and customs seizures

Data comes in four ways:

| Technique | What it does |
|---|---|
| **APIs** | Connectors for the Met, the Art Institute of Chicago, the Cleveland Museum of Art and the Smithsonian National Museum of African Art |
| **Web scraping** | A configurable, robots.txt-respecting HTML scraper for auction results and collection sites that have no API |
| **Webhooks** | Inbound (partners push signed records) and outbound (subscribe to signed event notifications, with retries and a delivery log) |
| **WebSockets** | `/ws` streams every new artifact, sale, provenance step, case update and sync result live; the dashboard uses it |

Only sub-Saharan material is stored. Every record is placed by country, culture or region
(`app/regions.py` knows the 49 countries, historical names such as Dahomey, Gold Coast and Zaire, and
about 130 cultures). Records that cannot be placed are rejected with HTTP 422.

## Quick start

You need Python 3.11 or newer. Then:

- **Windows:** double-click `run.bat`
- **macOS / Linux:** run `./run.sh` in a terminal

The first run installs dependencies (about a minute). Then open http://127.0.0.1:8000.

Or set it up by hand:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.cli serve            # http://127.0.0.1:8000  (dashboard), /docs (API explorer)
```

Pull data from the museum APIs, from the dashboard's **Data sources** tab or from the command line:

```bash
python -m app.cli sync met --query "Benin" --limit 50
python -m app.cli sync artic --query "Yoruba" --limit 50
python -m app.cli sync cleveland --query "mask" --limit 50
ARTI_SMITHSONIAN_API_KEY=... python -m app.cli sync smithsonian --query "textile"
```

Run the tests with `pytest`. They use recorded API responses and need no network access.

## Android app

`android/` holds a small native Android app (APK, Android 5.0+) that shows the dashboard on your phone,
with the live feed included. The data and syncing stay on the server, so the app needs a running server
to connect to:

1. On your computer, start the server so the phone can reach it: double-click `run-for-phone.bat`
   (Windows) or run `./run-for-phone.sh`. It prints an address such as `http://192.168.1.20:8000`.
   If Windows asks, allow Python through the firewall on private networks.
2. Install `arti-gala-0.1.0.apk` on the phone. Allow "Install unknown apps" for your browser or file
   manager when Android asks.
3. Open Arti Gala, enter the address and tap **Connect**. Use the menu to reload or change the server.

The phone and the computer must be on the same Wi-Fi, unless the server is hosted online.

To rebuild the APK (Ubuntu/Debian, no Android Studio needed):

```bash
sudo apt install openjdk-17-jdk-headless aapt dalvik-exchange zipalign apksigner
curl -L -o android-34.jar https://raw.githubusercontent.com/Sable/android-platforms/master/android-34/android.jar
ANDROID_JAR=$PWD/android-34.jar android/build.sh     # -> android/build/arti-gala-0.1.0.apk
```

`android/arti-gala.keystore` (password `artigala`) signs the app. Keep using it so new builds install as
updates over the old app. It's a convenience key for a self-distributed app; make your own (and keep it
private) before publishing on Google Play.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ARTI_DATABASE_URL` | `sqlite:///./arti_gala.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `ARTI_INBOUND_WEBHOOK_SECRET` | unset (inbound disabled) | Shared secret partners sign pushes with |
| `ARTI_SMITHSONIAN_API_KEY` | unset | Free key from https://api.data.gov/signup/ |
| `ARTI_ALLOW_PRIVATE_WEBHOOK_TARGETS` | `false` | Allow webhook/scrape URLs on localhost/private networks |
| `ARTI_WEBHOOK_MAX_ATTEMPTS` | `3` | Delivery attempts, with exponential backoff |
| `ARTI_SCRAPE_DELAY` | `1.0` | Seconds between scraper requests to a site |
| `ARTI_USER_AGENT` | `ArtiGalaBot/0.1 (...)` | Sent with API and scraper requests |

## API overview

Full interactive docs are at `/docs`.

**Artifacts**
- `GET /artifacts?q=&country=&region=&culture=&object_type=&holder_kind=&year_from=&year_to=&has_auctions=&has_cases=`
- `POST /artifacts`: register an artifact (e.g. from a personal collection); upserts on `source` + `source_id`
- `GET /artifacts/{id}`: full record with holder, provenance, auctions and cases
- `GET /artifacts/{id}/journey`: every holder and place it has been, in order
- `GET /artifacts/{id}/history`: origin plus a readable timeline
- `POST /artifacts/{id}/provenance`: record a new movement (sale, loan, return…)

**Auctions**: `GET /auctions?house=&status=&currency=&min_price=&max_price=&year_from=`, `GET /auctions/stats`,
`POST /auctions`, `PUT /auctions/{id}/artifact` (link a lot to an artifact), `GET /auctions/{id}/candidates`
(artifacts that look like the lot)

**Cases**: `GET /cases?status=&case_type=&jurisdiction=&artifact_id=`, `POST /cases`, `PATCH /cases/{id}`,
`PUT /cases/{id}/artifacts/{artifact_id}`

**Holders & stats**: `GET /holders?kind=national_museum|private_collection|…`, `POST /holders`, `GET /stats`

**Sync**: `GET /sync/connectors`, `POST /sync/{connector}`, `POST /sync/scrape`, `GET /sync/jobs/{id}`

## Realtime: WebSocket

```js
const ws = new WebSocket("ws://localhost:8000/ws?topics=auction,case");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
// {"event": "auction.created", "data": {...}, "ts": "..."}
ws.send(JSON.stringify({ action: "subscribe", topics: ["artifact.*", "provenance"] }));
```

Events: `artifact.created`, `artifact.updated`, `provenance.added`, `auction.created`, `auction.updated`,
`case.created`, `case.updated` and `sync.finished`.

## Webhooks

**Outbound.** Subscribe a URL to receive the events above as POST requests:

```bash
curl -X POST localhost:8000/webhooks/subscriptions -H 'content-type: application/json' \
  -d '{"url": "https://example.org/hooks/arti", "events": ["auction.*", "case.*"]}'
```

The response includes a `secret`, shown only once. Every delivery carries
`X-ArtiGala-Signature: sha256=<HMAC-SHA256(secret, raw body)>`, plus `X-ArtiGala-Event` and
`X-ArtiGala-Delivery`. Failed deliveries are retried; check `GET /webhooks/subscriptions/{id}/deliveries`.
Targets on private networks are refused unless explicitly allowed.

**Inbound.** Museums, registries or auction houses can push records:

```bash
BODY='{"type":"case","data":{"title":"Claim for ...","case_type":"restitution_claim","artifact_refs":[{"source":"met","source_id":"1001"}]}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$ARTI_INBOUND_WEBHOOK_SECRET" | cut -d' ' -f2)"
curl -X POST localhost:8000/webhooks/inbound -H "X-ArtiGala-Signature: $SIG" -H 'content-type: application/json' -d "$BODY"
```

`type` is one of `artifact`, `auction`, `case` or `provenance`; `provenance` also needs an `artifact_ref`.

## Scraping sites without an API

A scraper is a JSON config of CSS selectors, so no code is needed. See
`scrapers/example_auction_results.json`:

```bash
python -m app.cli scrape scrapers/my_auction_house.json --limit 200
# or: POST /sync/scrape with the config as the body
```

Field selectors are `"css"` (text), `"css@attr"` (an attribute) or `"@attr"` (an attribute of the item
itself). For auction lots the scraper parses estimates and prices in any common format (`£3,000–5,000`,
`EUR 3.200,50`, `US$ 45k`), infers the status (sold, unsold, withdrawn), follows pagination and drops
lots that are not sub-Saharan. It checks robots.txt, waits between requests and identifies itself with
a User-Agent. Before adding a site, check its terms of use; many auction houses forbid scraping or
offer licensed data feeds instead.

## How provenance is parsed

Museum provenance usually reads like *"Collected by X, Kasai, 1905; sold, Christie's, London, 1970,
lot 45, to Private collection, Brussels; purchased by the museum, 1990."* `app/services/provenance.py`
splits this into events and assigns each an event type (looted, sold, donated, inherited, restituted…),
a holder, a place and years. Sales at known auction houses become auction lots linked to the artifact.
This parsing is heuristic, so each event keeps the original text in `description`.

## Project layout

```
app/
  main.py            FastAPI app factory (lifespan binds the event bus + webhook dispatcher)
  models.py          Artifact, Holder, ProvenanceEvent, AuctionLot, LegalCase, webhooks, sync jobs
  regions.py         sub-Saharan country / culture / region classifier
  connectors/        met, artic, cleveland, smithsonian API clients + configurable HTML scraper
  services/          ingest (upserts), provenance parser, money parser, event bus, webhooks, sync runner
  api/               REST routes + /ws WebSocket
  static/index.html  dashboard (search, artifact journey/history, auctions, cases, live feed)
tests/               unit + API tests with mocked HTTP
```

## Limitations

- The connectors follow each museum's published API format but are tested only against recorded
  responses. Run a small sync first to confirm they still match the live APIs.
- Provenance and place parsing is heuristic; check important records against the source.
- Prices are stored in their original currency; there is no currency conversion.
- Syncs started from the CLI don't notify WebSocket clients or webhooks. Use the API (`POST /sync/...`)
  when you want live events.

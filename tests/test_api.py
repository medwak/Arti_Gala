import json

from app.services.webhooks import sign, verify

from .conftest import INBOUND_SECRET
from .test_connectors import AIC_RESPONSE


def test_artifact_detail_journey_and_history(client, benin_head):
    a = benin_head
    assert a["origin_country"] == "Nigeria"
    assert a["origin_region"] == "West Africa"
    assert a["current_holder"]["kind"] == "national_museum"
    assert [p["event_type"] for p in a["provenance"]] == ["created", "looted", "sold"]
    assert a["auction_count"] == 1 and a["auctions"][0]["hammer_price"] == 500

    journey = client.get(f"/artifacts/{a['id']}/journey").json()
    assert journey["locations"] == ["Nigeria", "Benin City", "London", "Testville"]
    assert journey["origin"] == "Edo peoples, Nigeria"

    history = client.get(f"/artifacts/{a['id']}/history").json()
    assert history["origin"]["year_start"] == 1500
    assert history["timeline"][1] == "1897: looted — British forces (Benin City)"

    # the private collection from provenance is registered as a holder
    holders = client.get("/holders", params={"kind": "private_collection"}).json()
    assert [h["name"] for h in holders["items"]] == ["Private collection"]


def test_rejects_non_sub_saharan_artifact(client):
    r = client.post("/artifacts", json={"title": "Amphora", "origin_country": "Greece"})
    assert r.status_code == 422
    assert "sub-Saharan" in r.json()["detail"]


def test_upsert_is_idempotent(client, benin_head):
    r = client.post("/artifacts", json={"source": "test", "source_id": "head-1", "title": "Commemorative head of an Oba",
                                        "origin_country": "Nigeria"})
    assert r.status_code == 201
    assert r.json()["id"] == benin_head["id"]
    assert client.get("/artifacts").json()["total"] == 1


def test_search_filters(client, benin_head):
    client.post("/artifacts", json={"title": "Ndop figure", "culture": "Kuba", "object_type": "Sculpture",
                                    "holder": {"name": "Jane Doe collection", "kind": "private_collection"}})
    client.post("/artifacts", json={"title": "Beaded necklace", "culture": "Maasai", "object_type": "Ornament"})

    def titles(**params):
        return sorted(a["title"] for a in client.get("/artifacts", params=params).json()["items"])

    assert titles(q="brass") == ["Commemorative head of an Oba"]
    assert titles(region="Central") == ["Ndop figure"]
    assert titles(country="Kenya") == ["Beaded necklace"]
    assert titles(object_type="ornament") == ["Beaded necklace"]
    assert titles(holder_kind="private_collection") == ["Ndop figure"]
    assert titles(holder_kind="national_museum") == ["Commemorative head of an Oba"]
    assert titles(has_auctions=True) == ["Commemorative head of an Oba"]
    assert titles(year_from=1400, year_to=1600) == ["Commemorative head of an Oba"]

    page = client.get("/artifacts", params={"limit": 2, "sort": "title"}).json()
    assert page["total"] == 3 and len(page["items"]) == 2


def test_auctions_and_stats(client, benin_head):
    client.post("/auctions", json={"auction_house": "House B", "title": "Dogon figure", "culture": "Dogon",
                                   "currency": "USD", "estimate_low": 1000, "estimate_high": 2000,
                                   "premium_price": 2500, "status": "sold", "sale_date": "2023-06-01"})
    client.post("/auctions", json={"auction_house": "House B", "title": "Senufo mask", "culture": "Senufo",
                                   "currency": "USD", "hammer_price": 900, "status": "sold"})
    assert client.post("/auctions", json={"auction_house": "X", "title": "Ming bowl"}).status_code == 422

    lots = client.get("/auctions", params={"currency": "USD", "min_price": 1000}).json()
    assert [lot["title"] for lot in lots["items"]] == ["Dogon figure"]
    assert lots["items"][0]["sale_year"] == 2023

    stats = client.get("/auctions/stats").json()
    assert stats["total_lots"] == 3
    usd = next(c for c in stats["by_currency"] if c["currency"] == "USD")
    assert (usd["sold"], usd["max_price"], usd["avg_price"]) == (2, 2500, 1700)

    lot_id = lots["items"][0]["id"]
    candidates = client.get(f"/auctions/{lot_id}/candidates").json()
    assert candidates[0]["artifact_id"] == benin_head["id"]
    linked = client.put(f"/auctions/{lot_id}/artifact", json={"artifact_id": benin_head["id"]}).json()
    assert linked["artifact_id"] == benin_head["id"]
    assert len(client.get(f"/artifacts/{benin_head['id']}/auctions").json()) == 2


def test_cases(client, benin_head):
    r = client.post("/cases", json={"title": "Restitution claim for the head", "case_type": "restitution_claim",
                                    "claimant": "Claimant", "respondent": "National Museum Test",
                                    "jurisdiction": "Testland", "artifact_ids": [benin_head["id"]]})
    assert r.status_code == 201
    case = r.json()
    assert case["artifact_ids"] == [benin_head["id"]]

    updated = client.patch(f"/cases/{case['id']}", json={"status": "returned", "resolved_date": "2024-01-02"}).json()
    assert updated["status"] == "returned"
    assert client.get("/cases", params={"status": "returned"}).json()["total"] == 1
    assert client.get("/cases", params={"artifact_id": benin_head["id"]}).json()["total"] == 1
    assert client.get("/artifacts", params={"has_cases": True}).json()["total"] == 1
    assert client.post("/cases", json={"title": "x", "artifact_ids": [999]}).status_code == 404

    stats = client.get("/stats").json()
    assert stats["cases"] == 1 and stats["open_cases"] == 0
    assert stats["by_country"] == {"Nigeria": 1}


def test_websocket_receives_live_events(client):
    with client.websocket_connect("/ws?topics=auction,case") as ws:
        assert ws.receive_json()["event"] == "welcome"
        client.post("/artifacts", json={"title": "Ignored by topic filter", "culture": "Dogon"})
        client.post("/auctions", json={"auction_house": "H", "title": "Baule mask", "culture": "Baule"})
        message = ws.receive_json()
        assert message["event"] == "auction.created"
        assert message["data"]["title"] == "Baule mask"

        ws.send_json({"action": "subscribe", "topics": ["artifact.*"]})
        assert ws.receive_json()["event"] == "subscribed"
        client.post("/artifacts", json={"title": "Chi wara headdress", "culture": "Bamana"})
        message = ws.receive_json()
        assert message["event"] == "artifact.created"
        assert message["data"]["origin_country"] == "Mali"

        ws.send_json({"action": "ping"})
        assert ws.receive_json()["event"] == "pong"


def test_outbound_webhooks_are_signed(client, recorder):
    sub = client.post("/webhooks/subscriptions", json={"url": "https://hooks.example.test/in", "events": ["case.*"]}).json()
    assert len(sub["secret"]) >= 32
    client.post("/artifacts", json={"title": "Not a case event", "culture": "Lobi"})
    client.post("/cases", json={"title": "Customs seizure", "case_type": "customs_seizure"})

    requests = recorder.wait_for(1)
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["X-ArtiGala-Event"] == "case.created"
    assert verify(sub["secret"], request.content, request.headers["X-ArtiGala-Signature"])
    assert json.loads(request.content)["data"]["title"] == "Customs seizure"

    deliveries = []
    for _ in range(50):
        deliveries = client.get(f"/webhooks/subscriptions/{sub['id']}/deliveries").json()
        if deliveries:
            break
        recorder.wait_for(99, timeout=0.05)
    assert deliveries[0]["success"] is True and deliveries[0]["status_code"] == 200


def test_outbound_webhook_retries_then_records_failure(client, recorder):
    recorder.status = 503
    sub = client.post("/webhooks/subscriptions", json={"url": "https://hooks.example.test/in"}).json()
    assert client.post(f"/webhooks/subscriptions/{sub['id']}/test").json() == {"delivered": False}
    assert len(recorder.requests) == 2  # webhook_max_attempts
    delivery = client.get(f"/webhooks/subscriptions/{sub['id']}/deliveries").json()[0]
    assert (delivery["attempts"], delivery["success"], delivery["error"]) == (2, False, "HTTP 503")


def test_webhook_url_validation(client, settings):
    assert client.post("/webhooks/subscriptions", json={"url": "ftp://example.com/x"}).status_code == 422
    settings.allow_private_webhook_targets = False
    assert client.post("/webhooks/subscriptions", json={"url": "http://127.0.0.1:9/x"}).status_code == 422


def _signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {"X-ArtiGala-Signature": sign(INBOUND_SECRET, body), "Content-Type": "application/json"}


def test_inbound_webhook(client, benin_head):
    body, headers = _signed({"type": "auction", "data": {
        "source": "partner", "source_id": "p-1", "auction_house": "Partner House", "title": "Lot",
        "artifact_ref": {"source": "test", "source_id": "head-1"}, "status": "upcoming"}})
    r = client.post("/webhooks/inbound", content=body, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["events"] == ["auction.created"]

    body, headers = _signed({"type": "provenance", "artifact_ref": {"source": "test", "source_id": "head-1"},
                             "data": {"event_type": "restituted", "holder_name": "Returned Holder",
                                      "holder_kind": "national_museum", "location": "Benin City",
                                      "year_start": 2025, "sets_current_holder": True}})
    assert client.post("/webhooks/inbound", content=body, headers=headers).status_code == 202
    detail = client.get(f"/artifacts/{benin_head['id']}").json()
    assert detail["provenance"][-1]["event_type"] == "restituted"
    assert detail["current_holder"]["name"] == "Returned Holder"
    assert detail["auction_count"] == 2

    bad = client.post("/webhooks/inbound", content=body, headers={"X-ArtiGala-Signature": "sha256=deadbeef"})
    assert bad.status_code == 401


def test_sync_job_from_museum_api(client, http_routes):
    http_routes["https://api.artic.edu/api/v1/artworks/search"] = AIC_RESPONSE
    with client.websocket_connect("/ws?topics=sync") as ws:
        ws.receive_json()
        job = client.post("/sync/artic", json={"query": "mask", "limit": 5}).json()
        finished = ws.receive_json()
    assert finished["event"] == "sync.finished"
    job = client.get(f"/sync/jobs/{job['id']}").json()
    assert (job["status"], job["fetched"], job["created"]) == ("succeeded", 1, 2), job  # artifact + provenance sale
    artifact = client.get("/artifacts", params={"source": "artic"}).json()["items"][0]
    assert artifact["title"] == "Mask (Mukenga)" and artifact["auction_count"] == 1

    # re-running finds nothing new
    job2 = client.post("/sync/artic", json={"query": "mask", "limit": 5}).json()
    job2 = client.get(f"/sync/jobs/{job2['id']}").json()
    assert (job2["created"], job2["updated"]) == (0, 0)


def test_sync_unknown_connector(client):
    assert client.post("/sync/nope", json={}).status_code == 404


def test_sync_failure_is_reported(client):
    job = client.post("/sync/met", json={"query": "x"}).json()  # no mock route -> 404
    job = client.get(f"/sync/jobs/{job['id']}").json()
    assert job["status"] == "failed" and "404" in job["error"]


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Arti Gala" in r.text


def test_countries_list_all_49_with_counts(client, benin_head):
    countries = client.get("/countries").json()
    assert len(countries) == 49
    by_name = {c["country"]: c for c in countries}
    assert by_name["Nigeria"]["artifact_count"] == 1 and by_name["Nigeria"]["region"] == "West Africa"
    assert by_name["Kenya"]["artifact_count"] == 0
    assert {c["region"] for c in countries} == {"West Africa", "Central Africa", "East Africa", "Southern Africa"}


def test_country_filter_is_exact(client):
    client.post("/artifacts", json={"title": "Zarma blanket", "origin_country": "Niger"})
    client.post("/artifacts", json={"title": "Ibeji", "origin_country": "Nigeria"})
    titles = [a["title"] for a in client.get("/artifacts", params={"country": "Niger"}).json()["items"]]
    assert titles == ["Zarma blanket"]


def test_sources_list_connectors_and_stored_sources(client, benin_head):
    sources = {s["source"]: s for s in client.get("/sources").json()}
    assert {"europeana", "vam", "met", "artic", "cleveland", "smithsonian"} <= set(sources)
    assert sources["vam"]["continent"] == "Europe" and sources["europeana"]["continent"] == "Europe"
    assert sources["test"]["artifact_count"] == 1 and sources["test"]["syncable"] is False

    connectors = {c["name"]: c for c in client.get("/sync/connectors").json()}
    assert connectors["smithsonian"]["available"] is False
    assert connectors["smithsonian"]["needs"] == "ARTI_SMITHSONIAN_API_KEY"
    assert client.post("/sync/smithsonian", json={}).status_code == 422


def test_sync_all_for_one_country(client, http_routes):
    from .test_connectors import AIC_RESPONSE, VAM_DETAIL, VAM_SEARCH

    seen = []

    def vam(request):
        seen.append(str(request.url))
        return VAM_SEARCH

    http_routes.update({
        "https://api.artic.edu/api/v1/artworks/search": AIC_RESPONSE,
        "https://api.vam.ac.uk/v2/objects/search": vam,
        "https://api.vam.ac.uk/v2/object/O1234": VAM_DETAIL,
    })
    jobs = client.post("/sync/all", json={"country": "nigeria", "limit": 5}).json()
    assert {j["connector"] for j in jobs} == {"europeana", "vam", "met", "artic", "cleveland"}  # no key for smithsonian
    assert all(j["query"] == "Nigeria" for j in jobs)
    status = {j["connector"]: j for j in client.get("/sync/jobs").json()}
    assert status["vam"]["status"] == "succeeded" and status["vam"]["created"] == 1
    assert status["met"]["status"] == "failed"  # not mocked: one source failing doesn't stop the others
    assert "q_place_name=Nigeria" in seen[0]
    assert client.get("/artifacts", params={"country": "Nigeria", "source": "vam"}).json()["total"] == 1
    assert client.post("/sync/all", json={"country": "France"}).status_code == 422

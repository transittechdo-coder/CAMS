"""Guards' phones: connect with one QR code (no typing), sign in with the app's token, disconnect."""

import json
import socket
import time

from fastapi.testclient import TestClient


def test_phone_connects_with_qr_code_and_can_be_disconnected(admin, system, client):
    from cams.api import create_app

    r = admin.post("/api/phones/code", json={"new_guard": "Hamisi Juma"})
    assert r.status_code == 200
    q = r.json()
    assert q["user"]["full_name"] == "Hamisi Juma" and q["qr"].startswith("<svg")
    assert f"#pair={q['code']}" in q["url"] and "/guard" in q["url"]
    guard_user = q["user"]["username"]
    assert next(u for u in admin.get("/api/users").json() if u["username"] == guard_user)["role"] == "viewer"

    # the phone (a different client, not signed in) connects with the code: no password
    with TestClient(create_app(system)) as phone:
        assert phone.post("/api/phones/pair", json={"code": "WRONG123"}).status_code == 403
        p = phone.post("/api/phones/pair", json={"code": q["code"].lower(), "device": "Tecno Spark 10"}).json()
        token = p["token"]
        assert p["user"]["full_name"] == "Hamisi Juma" and p["site_name"] == "Test School"
    # the app signs in with "Authorization: Bearer"
    with TestClient(create_app(system)) as app_client:
        hdr = {"Authorization": f"Bearer {token}"}
        assert app_client.get("/api/status", headers=hdr).json()["user"]["username"] == guard_user
        assert app_client.get("/api/alerts/emergencies", headers=hdr).status_code == 200
        assert app_client.get("/api/alerts/emergencies").status_code == 401
        assert app_client.post("/api/phones/code", json={"new_guard": "x"}, headers=hdr).status_code == 403   # guards cannot add phones
        phones = admin.get("/api/phones").json()
        assert [(x["name"], x["full_name"]) for x in phones] == [("Tecno Spark 10", "Hamisi Juma")]
        # lost phone: disconnect it, and it is signed out at once
        admin.delete(f"/api/phones/{phones[0]['id']}")
        assert app_client.get("/api/alerts/emergencies", headers=hdr).status_code == 401
    assert admin.get("/api/phones").json() == []


def test_code_expires_and_has_few_uses(admin, system):
    uid = admin.get("/api/users").json()[0]["id"]
    q = admin.post("/api/phones/code", json={"user_id": uid}).json()
    for _ in range(3):
        system.phones.pair(q["code"], "phone")
    try:
        system.phones.pair(q["code"], "phone")
        raise AssertionError("a code must not work more than 3 times")
    except PermissionError:
        pass
    q = admin.post("/api/phones/code", json={"user_id": uid}).json()
    system.phones._codes[q["code"]]["expires"] = time.time() - 1
    try:
        system.phones.pair(q["code"], "phone")
        raise AssertionError("an old code must not work")
    except PermissionError:
        pass
    assert admin.post("/api/phones/code", json={}).status_code == 400


def test_app_download_and_visitor_check_out_by_guard(admin, client, system):
    from cams.api import create_app

    assert client.get("/app/CAMS-Guard.apk").status_code in (200, 404)
    assert "available" in admin.get("/api/phones/app").json()
    v = admin.post("/api/visitors", json={"full_name": "Asha", "hours": 1}).json()
    q = admin.post("/api/phones/code", json={"new_guard": "Gate guard"}).json()
    token = system.phones.pair(q["code"], "phone")["token"]
    with TestClient(create_app(system)) as phone:
        r = phone.post(f"/api/visitors/{v['id']}/checkout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and not r.json()["inside"]


def test_phones_find_cams_on_the_wifi(system):
    system.phones.start_discovery(8765)
    time.sleep(0.3)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        s.sendto(b"CAMS?", ("127.0.0.1", 8766))
        data, _ = s.recvfrom(512)
    finally:
        s.close()
    j = json.loads(data)
    assert j["cams"] == 1 and j["port"] == 8765 and j["site"] == system.db.get_setting("site_name")

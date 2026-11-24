"""Stage 1 test: a fake incoming message is stored against the right client.

Uses a throwaway SQLite DB and a client with no active modules, so no LLM
call is made — this validates the core engine only.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "sqlite:///./test_stage1.db"
os.environ["CONFIG_DIR"] = tempfile.mkdtemp(prefix="agency-test-configs-")

import pytest
from fastapi.testclient import TestClient

from app import models
from app.config_loader import save_client_config
from app.database import Base, SessionLocal, engine
from app.main import app


@pytest.fixture()
def api():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    client_a = models.Client(business_name="Test Biz A", active_modules=[])
    client_b = models.Client(business_name="Test Biz B", active_modules=[])
    db.add_all([client_a, client_b])
    db.commit()
    db.refresh(client_a)
    db.refresh(client_b)
    save_client_config(client_a.id, {"faqs": []})
    save_client_config(client_b.id, {"faqs": []})
    db.close()
    yield TestClient(app), client_a.id, client_b.id
    engine.dispose()


def test_message_stored_against_right_client(api):
    http, a_id, b_id = api
    res = http.post("/webhook", json={
        "client_id": a_id, "channel": "widget", "sender_id": "cust-1", "text": "hello there",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "open"
    assert body["reply"] is None  # no reply module active

    convos_a = http.get(f"/clients/{a_id}/conversations").json()
    convos_b = http.get(f"/clients/{b_id}/conversations").json()
    assert len(convos_a) == 1
    assert convos_a[0]["messages"][0]["text"] == "hello there"
    assert convos_a[0]["messages"][0]["role"] == "customer"
    assert convos_b == []  # never bleeds into another client


def test_followup_lands_in_same_conversation(api):
    http, a_id, _ = api
    http.post("/webhook", json={"client_id": a_id, "sender_id": "cust-2", "text": "first"})
    http.post("/webhook", json={"client_id": a_id, "sender_id": "cust-2", "text": "second"})
    convos = http.get(f"/clients/{a_id}/conversations").json()
    assert len(convos) == 1
    assert [m["text"] for m in convos[0]["messages"]] == ["first", "second"]


def test_unknown_client_rejected(api):
    http, _, _ = api
    res = http.post("/webhook", json={"client_id": 9999, "sender_id": "x", "text": "hi"})
    assert res.status_code == 404

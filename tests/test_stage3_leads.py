"""Stage 3 test: lead qualification flow, deterministic (LLM verdict mocked)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_stage1.db")
os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="agency-test-configs-"))

import pytest
from fastapi.testclient import TestClient

from app import models
from app.config_loader import save_client_config
from app.database import Base, SessionLocal, engine
from app.main import app
from app.modules import lead_qualifier

LEAD_CONFIG = {
    "lead_intro": "Welcome!",
    "qualifying_questions": [
        {"key": "budget", "question": "What's your budget?"},
        {"key": "timeline", "question": "When do you need it?"},
    ],
    "qualification_criteria": "Budget over 50",
    "lead_outro": "Thanks, we'll call you.",
}


@pytest.fixture()
def api(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    client = models.Client(business_name="Lead Biz", active_modules=["lead_qualifier"])
    db.add(client)
    db.commit()
    db.refresh(client)
    save_client_config(client.id, LEAD_CONFIG)
    db.close()
    monkeypatch.setattr(lead_qualifier, "_evaluate",
                        lambda config, answers, llm: ("qualified", "mocked verdict"))
    yield TestClient(app), client.id


def _send(http, cid, text):
    res = http.post("/webhook", json={"client_id": cid, "sender_id": "lead-1", "text": text})
    assert res.status_code == 200, res.text
    return res.json()


def test_full_lead_flow(api):
    http, cid = api
    r1 = _send(http, cid, "Hi, I'm interested")
    assert r1["reply"] == "Welcome! What's your budget?"

    r2 = _send(http, cid, "80 lakhs")
    assert r2["reply"] == "When do you need it?"

    r3 = _send(http, cid, "next month")
    assert r3["reply"] == "Thanks, we'll call you."

    leads = http.get(f"/clients/{cid}/leads").json()
    assert len(leads) == 1
    assert leads[0]["lead_status"] == "qualified"
    assert leads[0]["answers"] == {"budget": "80 lakhs", "timeline": "next month"}
    assert leads[0]["reason"] == "mocked verdict"


def test_leads_endpoint_empty_before_flow_completes(api):
    http, cid = api
    _send(http, cid, "Hi")  # only the intro question asked so far
    assert http.get(f"/clients/{cid}/leads").json() == []

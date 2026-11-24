"""Stage 5 test: report generation with no LLM key -> stats fallback template."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_stage1.db")
os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="agency-test-configs-"))

import pytest

from app import models
from app.database import Base, SessionLocal, engine
from app.modules import report_agent


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(report_agent, "REPORTS_DIR", tmp_path)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session, tmp_path
    session.close()


def test_report_fallback_without_llm(db):
    session, tmp_path = db
    client = models.Client(business_name="Report Biz", active_modules=["auto_report"])
    session.add(client)
    session.commit()
    session.refresh(client)
    session.add_all([
        models.Conversation(client_id=client.id, sender_id="a", status="escalated",
                            messages=[{"role": "customer", "text": "price?"}]),
        models.Conversation(client_id=client.id, sender_id="b", status="resolved",
                            messages=[{"role": "customer", "text": "hours?"}]),
        models.Conversation(client_id=client.id, sender_id="c", status="open",
                            lead_status="qualified", messages=[]),
    ])
    session.commit()

    text = report_agent.generate_report(session, client)  # no key -> fallback
    assert "Report Biz" in text
    assert "Conversations: 3" in text
    assert "Escalated to you: 1" in text
    assert "1 qualified" in text
    assert list(tmp_path.glob("client_*.txt"))  # report file written

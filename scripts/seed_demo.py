"""Seed the demo client: Sharma Dental Clinic (the proof-asset business).

Run: python -m scripts.seed_demo
Idempotent — skips if the client already exists.
"""
from app import models
from app.config_loader import save_client_config
from app.database import Base, SessionLocal, engine

DEMO_CONFIG = {
    "faqs": [
        {"q": "What are your opening hours?",
         "a": "Mon-Sat 9:30am-7pm, closed Sundays."},
        {"q": "Do you do teeth whitening?",
         "a": "Yes — in-clinic whitening, single session, results same day."},
        {"q": "How much does a general checkup cost?",
         "a": "Rs. 500, which includes a consultation with Dr. Sharma."},
        {"q": "Do you accept insurance?",
         "a": "We accept all major cashless insurance for procedures above Rs. 5,000."},
        {"q": "How do I book an appointment?",
         "a": "Reply here with your preferred day and time, or call 98765-43210."},
    ],
    "services": ["General checkup", "Teeth whitening", "Root canal", "Braces & aligners", "Extractions"],
    "pricing": {"General checkup": "Rs. 500", "Teeth whitening": "Rs. 6,000", "Root canal": "Rs. 4,500 - 8,000 depending on tooth"},
    "hours": "Mon-Sat 9:30am-7pm, closed Sundays",
    "extra_facts": ["Located in Sector 17, Chandigarh", "Dr. Sharma has 15 years of experience"],
    "never_say": ["No discount promises", "No refund guarantees", "No medical advice"],
}


LEADS_CONFIG = {
    "faqs": [
        {"q": "Where are your properties located?",
         "a": "We have 2BHK and 3BHK flats in Zirakpur and Mohali, ready to move."},
    ],
    "lead_intro": "Happy to help you find the right flat! A couple of quick questions first.",
    "qualifying_questions": [
        {"key": "budget", "question": "What's your budget range (in lakhs)?"},
        {"key": "timeline", "question": "When are you looking to buy — within 3 months, 6 months, or just exploring?"},
        {"key": "location", "question": "Which area do you prefer — Zirakpur, Mohali, or either?"},
    ],
    "qualification_criteria": (
        "Qualified if budget is at least 40 lakhs AND timeline is within 6 months "
        "AND location is Zirakpur, Mohali, or no preference. Otherwise unqualified."
    ),
    "lead_outro": "Thanks! Our property advisor will call you shortly with matching options.",
}


def _seed_client(db, business_name: str, industry: str, tone: str, contact: str,
                 modules: list, config: dict) -> None:
    existing = db.query(models.Client).filter_by(business_name=business_name).first()
    if existing:
        existing.active_modules = modules
        db.commit()
        save_client_config(existing.id, config)
        print(f"Updated existing client '{business_name}' (id={existing.id})")
        return
    client = models.Client(
        business_name=business_name, industry=industry, tone_of_voice=tone,
        escalation_contact=contact, active_modules=modules,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    save_client_config(client.id, config)
    print(f"Seeded client '{business_name}' id={client.id} -> configs/client_{client.id}.json")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_client(
            db, "Sharma Dental Clinic", "dental clinic",
            "warm, reassuring, concise", "dr.sharma@example.com",
            ["reply_agent", "auto_report"], DEMO_CONFIG,
        )
        _seed_client(
            db, "Verma Realty", "real estate",
            "professional and helpful", "verma.realty@example.com",
            ["lead_qualifier", "reply_agent"], LEADS_CONFIG,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

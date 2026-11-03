"""Backfill: listing phones → contacts (PHASE 7.5 gap fix).

A discovery listing phone (businesses.phone, from gmaps/serpapi) lived
only on the business row; leads are built from contacts, so phone-only
businesses never became leads. backfill_listing_phones promotes them.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.backfill import backfill_listing_phones
from app.db import METADATA


def _fresh_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    return engine


def _add_business(conn, key: str, name: str, phone: str) -> int:
    conn.execute(
        text(
            """
            INSERT INTO businesses (key, name, phone, website, domain,
                                    industry_match, source)
            VALUES (:k, :n, :p, '', '', 0, 'gmaps_scrape')
            """
        ),
        {"k": key, "n": name, "p": phone},
    )
    row = conn.execute(
        text("SELECT id FROM businesses WHERE key = :k"), {"k": key}
    ).first()
    return row[0]


def test_promotes_phone_into_contacts() -> None:
    engine = _fresh_engine()
    with engine.begin() as conn:
        bid = _add_business(conn, "b1", "Warung Kopi", "081234567890")
    stats = backfill_listing_phones(engine)
    assert stats["inserted"] == 1
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kind, value, source_kind, confidence FROM contacts")
        ).all()
    assert rows == [("phone", "081234567890", "listing", 50)]


def test_idempotent_no_duplicate() -> None:
    engine = _fresh_engine()
    with engine.begin() as conn:
        _add_business(conn, "b1", "Warung Kopi", "081234567890")
    first = backfill_listing_phones(engine)
    second = backfill_listing_phones(engine)
    assert first["inserted"] == 1
    assert second["inserted"] == 0  # phone contact exists → skip


def test_skips_business_without_phone() -> None:
    engine = _fresh_engine()
    with engine.begin() as conn:
        _add_business(conn, "b1", "Warung Kopi", "")
    stats = backfill_listing_phones(engine)
    assert stats["inserted"] == 0


def test_skips_business_with_existing_phone_contact() -> None:
    """A crawl-extracted phone contact already present → no new row."""
    engine = _fresh_engine()
    with engine.begin() as conn:
        bid = _add_business(conn, "b1", "Warung Kopi", "081234567890")
        conn.execute(
            text(
                """
                INSERT INTO contacts (business_id, kind, value, value_norm,
                                      source_kind, confidence, status)
                VALUES (:bid, 'phone', '+6281234567890', '+6281234567890',
                        'text', 60, 'unknown')
                """
            ),
            {"bid": bid},
        )
    stats = backfill_listing_phones(engine)
    assert stats["inserted"] == 0


def test_lead_now_built_from_listing_phone() -> None:
    """End to end: phone-only business becomes a lead after backfill."""
    from app.leads import build_leads

    engine = _fresh_engine()
    with engine.begin() as conn:
        _add_business(conn, "b1", "Warung Kopi", "081234567890")
    backfill_listing_phones(engine)
    stats = build_leads(engine)
    assert stats["new"] == 1
    with engine.connect() as conn:
        lead = conn.execute(
            text("SELECT best_phone, score FROM leads")
        ).first()
    assert lead[0] == "081234567890"
    assert lead[1] >= 20  # phone points

"""Backfill: promote listing phones (businesses.phone) into contacts.

Why: discovery sources (gmaps/serpapi/places) save the listing phone on
businesses.phone, but leads are built ONLY from the contacts table
(crawl-extracted). A business without a website therefore never becomes
a lead even though we hold its phone — the exact data the operator
wants. This helper copies business phones into contacts (kind='phone',
source_kind='listing', confidence 50) so build_leads picks them up.

Idempotent: skips businesses that already have a phone contact.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)


def backfill_listing_phones(engine: Engine) -> dict:
    """Copy businesses.phone → contacts(kind='phone') where missing.

    Returns {"checked": n, "inserted": n, "with_phone": n}.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT b.id, b.phone
                FROM businesses b
                WHERE b.phone IS NOT NULL AND b.phone != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM contacts c
                    WHERE c.business_id = b.id AND c.kind = 'phone'
                  )
                """
            )
        ).all()

    inserted = 0
    for business_id, phone in rows:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO contacts
                      (business_id, crawl_job_id, kind, value, value_norm,
                       source_url, source_kind, confidence, status)
                    VALUES
                      (:bid, NULL, 'phone', :val, :norm, '', 'listing', 50,
                       'unknown')
                    """
                ),
                {"bid": business_id, "val": phone, "norm": phone.strip()},
            )
        inserted += 1

    result = {
        "checked": len(rows),
        "inserted": inserted,
        "with_phone": len(rows),
    }
    if inserted:
        log.info("backfill_listing_phones: %s phones promoted", inserted)
    return result

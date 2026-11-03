"""Outreach engine (PHASE 6).

SMTP client, templates, personalization, campaign runner, suppression,
unsubscribe, follow-up scheduler. DRY RUN is the default and the safe
mode: without an explicit DRY_RUN=false AND complete SMTP credentials,
nothing ever leaves the machine — every send is logged as `sent-dry`.

Layout: smtp.py (transport), template.py (render), campaign.py
(campaign lifecycle + runner), unsubscribe.py (one-click), __init__.
"""

from app.outreach.campaign import run_campaign, create_campaign
from app.outreach.template import render_message

__all__ = ["run_campaign", "create_campaign", "render_message"]

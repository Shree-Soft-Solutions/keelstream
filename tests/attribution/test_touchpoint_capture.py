"""
Unit & Integration Tests for Client-Side Touchpoint Capture & Server-Side Identity Binding
(Line of Work 4: Task 4.1)
"""

import os
import re
from datetime import datetime, timezone
import pytest

from core.attribution.identity import (
    IdentityRecord,
    IdentityResolver,
    IdentityStatus,
    Touchpoint,
    UnmatchedReason,
)


def test_keelstream_js_script_integrity():
    """Verify static/keelstream.js includes all required tracking features."""
    js_path = os.path.join("static", "keelstream.js")
    assert os.path.exists(js_path), "static/keelstream.js must exist"

    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify UTM parameter capture
    for utm in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]:
        assert utm in content, f"Script must extract {utm}"

    # Verify click ID capture
    for click_id in ["gclid", "fbclid", "msclkid", "ttclid"]:
        assert click_id in content, f"Script must extract {click_id}"

    # Verify DNT check and consent choices
    assert "doNotTrack" in content or "isDNTActive" in content, "Script must check browser Do Not Track"
    assert "setConsent" in content, "Script must expose consent management API"
    assert "/api/v1/track" in content, "Default beacon endpoint must be /api/v1/track"
    assert "getClientId" in content, "Script must generate and retrieve anonymous client ID"


def test_touchpoint_creation_and_payload_parsing():
    """Verify Touchpoint parses client-side beacons deterministically."""
    beacon = {
        "tenant_id": "tenant-corp-1",
        "anonymous_id": "ks_anon_12345",
        "session_id": "ks_ses_9988",
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "q4_enterprise_search",
        "utm_content": "headline_variant_a",
        "utm_term": "revenue attribution software",
        "click_id": "gclid_test_xyz789",
        "click_ids": {
            "gclid": "gclid_test_xyz789"
        },
        "url": "https://example.com/demo?utm_source=google&gclid=gclid_test_xyz789",
        "referrer": "https://www.google.com/",
        "timestamp": "2026-10-23T10:00:00Z",
        "consent_status": "GRANTED"
    }

    tp = IdentityResolver.from_tracking_payload(beacon)
    assert tp.tenant_id == "tenant-corp-1"
    assert tp.visitor_id == "ks_anon_12345"
    assert tp.session_id == "ks_ses_9988"
    assert tp.utm_source == "google"
    assert tp.utm_medium == "cpc"
    assert tp.utm_campaign == "q4_enterprise_search"
    assert tp.utm_content == "headline_variant_a"
    assert tp.utm_term == "revenue attribution software"
    assert tp.click_id == "gclid_test_xyz789"
    assert tp.click_ids["gclid"] == "gclid_test_xyz789"
    assert tp.consent_status == "GRANTED"


def test_anonymous_touchpoint_remains_explicitly_unmatched():
    """Verify anonymous visitors without CRM credentials remain explicitly unmatched."""
    resolver = IdentityResolver()
    tp = Touchpoint(
        id="tp-001",
        tenant_id="tenant-acme",
        visitor_id="ks_anon_unidentified_1",
        utm_source="linkedin",
        utm_medium="paid_social",
        utm_campaign="brand_awareness"
    )

    recorded_tp, identity = resolver.record_touchpoint(tp)
    assert recorded_tp.visitor_id == "ks_anon_unidentified_1"
    assert identity.status == IdentityStatus.UNMATCHED
    assert identity.is_matched is False
    assert identity.unmatched_reason == UnmatchedReason.NO_VERIFIED_IDENTIFIER.value
    assert identity.confidence_score == 0.0
    assert identity.verified_email is None


def test_identity_binding_on_verified_event():
    """Verify anonymous visitor ID is bound to verified CRM identity upon form submit or lead creation."""
    resolver = IdentityResolver()
    tenant_id = "tenant-acme"
    anonymous_id = "ks_anon_shopper_42"

    # Step 1: Initial anonymous touchpoint
    tp = Touchpoint(
        id="tp-init",
        tenant_id=tenant_id,
        visitor_id=anonymous_id,
        utm_source="google",
        utm_campaign="spring_sale",
        click_id="gclid_initial_abc"
    )
    resolver.record_touchpoint(tp)

    # Step 2: Form submission with verified email
    result = resolver.resolve_or_create(
        tenant_id=tenant_id,
        anonymous_id=anonymous_id,
        verified_email="buyer@enterprise.org",
        crm_contact_id="hubspot_contact_101",
        metadata={"form_name": "request_demo"}
    )

    assert result.success is True
    assert result.action in ("LINKED", "CREATED")
    identity = result.record
    assert identity.status == IdentityStatus.MATCHED
    assert identity.is_matched is True
    assert identity.unmatched_reason is None
    assert identity.confidence_score == 1.0
    assert identity.verified_email == "buyer@enterprise.org"
    assert identity.crm_contact_id == "hubspot_contact_101"
    assert anonymous_id in identity.linked_anonymous_ids

    # Query back by email and anonymous ID
    fetched_by_anon = resolver.get_identity(tenant_id, anonymous_id)
    assert fetched_by_anon is not None
    assert fetched_by_anon.verified_email == "buyer@enterprise.org"

    fetched_by_email = resolver.get_identity_by_email(tenant_id, "buyer@enterprise.org")
    assert fetched_by_email is not None
    assert fetched_by_email.id == identity.id


def test_multi_device_stitching_to_same_verified_identity():
    """Verify that multiple anonymous IDs from the same user link to one primary identity."""
    resolver = IdentityResolver()
    tenant = "tenant-fintech"
    email = "cfo@company.com"

    # Visitor browses on desktop
    res_desktop = resolver.resolve_or_create(
        tenant_id=tenant,
        anonymous_id="anon_desktop_11",
        verified_email=email
    )
    assert res_desktop.success is True

    # Same user later visits on mobile and signs in with same email
    res_mobile = resolver.resolve_or_create(
        tenant_id=tenant,
        anonymous_id="anon_mobile_22",
        verified_email=email
    )
    assert res_mobile.success is True
    assert res_mobile.action == "LINKED"

    primary = resolver.get_identity_by_email(tenant, email)
    assert primary is not None
    assert "anon_desktop_11" in primary.linked_anonymous_ids
    assert "anon_mobile_22" in primary.linked_anonymous_ids


def test_conflict_protection_does_not_silently_overwrite():
    """Verify that an anonymous ID cannot be overwritten with a conflicting verified identity."""
    resolver = IdentityResolver()
    tenant = "tenant-saas"
    anon_id = "shared_terminal_device_99"

    # User A binds identity
    res1 = resolver.resolve_or_create(
        tenant_id=tenant,
        anonymous_id=anon_id,
        verified_email="user_a@first.com"
    )
    assert res1.success is True
    assert res1.record.verified_email == "user_a@first.com"

    # User B attempts to bind same anonymous ID to a different email without force authorization
    res2 = resolver.resolve_or_create(
        tenant_id=tenant,
        anonymous_id=anon_id,
        verified_email="user_b@second.com",
        force_link=False
    )
    assert res2.success is False
    assert res2.action == "CONFLICT_PRESERVED"
    # Preserves user A
    assert res2.record.verified_email == "user_a@first.com"


def test_consent_denial_blocks_identity_resolution():
    """Verify that user consent denial prevents identity resolution."""
    resolver = IdentityResolver()
    tenant = "tenant-privacy"

    res = resolver.resolve_or_create(
        tenant_id=tenant,
        anonymous_id="anon_dnt_user",
        verified_email="private_user@proton.me",
        consent_status="DENIED"
    )

    assert res.success is True
    assert res.action == "CONSENT_BLOCKED"
    assert res.record.status == IdentityStatus.CONSENT_DENIED
    assert res.record.is_matched is False
    assert res.record.unmatched_reason == UnmatchedReason.CONSENT_DENIED.value
    assert res.record.confidence_score == 0.0
    assert res.record.verified_email is None


def test_strict_multi_tenant_isolation():
    """Verify Tenant A data is strictly invisible and segregated from Tenant B."""
    resolver = IdentityResolver()
    tenant_a = "tenant-alpha"
    tenant_b = "tenant-beta"
    shared_anon_id = "ks_anon_collision_id"

    # Tenant A sets up touchpoint and binds email
    resolver.resolve_or_create(
        tenant_id=tenant_a,
        anonymous_id=shared_anon_id,
        verified_email="alex@alpha.org"
    )

    # Tenant B queries same anonymous_id -> must be None
    assert resolver.get_identity(tenant_b, shared_anon_id) is None

    # Tenant B queries Tenant A's email -> must be None
    assert resolver.get_identity_by_email(tenant_b, "alex@alpha.org") is None

    # Empty tenant ID raises error
    with pytest.raises(ValueError):
        resolver.resolve_or_create(
            tenant_id="",
            anonymous_id="anon_x"
        )

"""
KeelStream Identity Resolution & Touchpoint Binding Module
===========================================================
Implements deterministic, explainable identity resolution linking anonymous
visitor touchpoints to verified CRM identities.

Key architectural rules:
1. Strict multi-tenant isolation on all storage and query operations.
2. Unmatched identities remain explicitly unmatched; never guess or synthesize links.
3. Never overwrite existing verified identities without explicit authorization.
4. Strictly respect user consent and Do Not Track choices.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class IdentityStatus(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    CONSENT_DENIED = "CONSENT_DENIED"
    CONFLICT_REJECTED = "CONFLICT_REJECTED"


class UnmatchedReason(str, Enum):
    NO_VERIFIED_IDENTIFIER = "NO_VERIFIED_IDENTIFIER"
    CONSENT_DENIED = "CONSENT_DENIED"
    AMBIGUOUS_CONFLICT = "AMBIGUOUS_CONFLICT"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    INVALID_FORMAT = "INVALID_FORMAT"


@dataclass
class Touchpoint:
    """Represents an immutable recorded user touchpoint."""
    id: str
    tenant_id: str
    visitor_id: str  # anonymous client ID
    session_id: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    click_id: Optional[str] = None  # primary click ID (gclid, fbclid, etc.)
    click_ids: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    referrer: Optional[str] = None
    ad_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consent_status: str = "GRANTED"
    raw_payload: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("Touchpoint must have a non-empty tenant_id.")
        if not self.visitor_id or not self.visitor_id.strip():
            raise ValueError("Touchpoint must have a non-empty visitor_id.")
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    @property
    def anonymous_id(self) -> str:
        return self.visitor_id


@dataclass
class IdentityRecord:
    """Represents an identity state for an anonymous visitor within a tenant."""
    id: str
    tenant_id: str
    anonymous_id: str
    verified_email: Optional[str] = None
    phone_hash: Optional[str] = None
    crm_contact_id: Optional[str] = None
    confidence_score: float = 0.0
    match_key: Optional[str] = None  # 'email', 'crm_contact_id', 'phone_hash'
    status: IdentityStatus = IdentityStatus.UNMATCHED
    is_matched: bool = False
    unmatched_reason: Optional[str] = None
    consent_status: str = "GRANTED"
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    linked_anonymous_ids: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("IdentityRecord must have a non-empty tenant_id.")
        if not self.anonymous_id or not self.anonymous_id.strip():
            raise ValueError("IdentityRecord must have a non-empty anonymous_id.")
        if self.first_seen_at.tzinfo is None:
            self.first_seen_at = self.first_seen_at.replace(tzinfo=timezone.utc)
        if self.last_seen_at.tzinfo is None:
            self.last_seen_at = self.last_seen_at.replace(tzinfo=timezone.utc)
        if self.anonymous_id:
            self.linked_anonymous_ids.add(self.anonymous_id)


@dataclass
class IdentityResolutionResult:
    """Outcome of an identity resolution or binding attempt."""
    record: IdentityRecord
    action: str  # 'CREATED', 'LINKED', 'RETAINED_UNMATCHED', 'CONFLICT_PRESERVED', 'CONSENT_BLOCKED'
    success: bool
    message: str


class IdentityResolver:
    """
    Deterministic identity resolution engine.
    Ensures strict tenant scoping and enforces explainable matching logic.
    """

    def __init__(self):
        # Tenant-isolated in-memory storage: tenant_id -> dict of anonymous_id -> IdentityRecord
        self._identities_by_anon: Dict[str, Dict[str, IdentityRecord]] = {}
        # Tenant-isolated index: tenant_id -> dict of verified_email -> IdentityRecord id
        self._identities_by_email: Dict[str, Dict[str, str]] = {}
        # Tenant-isolated touchpoint log: tenant_id -> list of Touchpoint
        self._touchpoints: Dict[str, List[Touchpoint]] = {}

    def _ensure_tenant(self, tenant_id: str) -> None:
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required and cannot be empty.")
        if tenant_id not in self._identities_by_anon:
            self._identities_by_anon[tenant_id] = {}
            self._identities_by_email[tenant_id] = {}
            self._touchpoints[tenant_id] = []

    @staticmethod
    def normalize_email(email: Optional[str]) -> Optional[str]:
        if not email or not isinstance(email, str):
            return None
        cleaned = email.strip().lower()
        # Basic sanity check
        if re.match(r"^[^@]+@[^@]+\.[^@]+$", cleaned):
            return cleaned
        return None

    def resolve_or_create(
        self,
        tenant_id: str,
        anonymous_id: str,
        verified_email: Optional[str] = None,
        phone_hash: Optional[str] = None,
        crm_contact_id: Optional[str] = None,
        consent_status: str = "GRANTED",
        force_link: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> IdentityResolutionResult:
        """
        Resolves or creates an identity record for an anonymous client ID.
        Adheres to fail-safe deterministic rules:
        - If consent is DENIED, no identity matching occurs.
        - If no verified identifier is supplied, record is explicitly UNMATCHED.
        - If conflicting verified emails are presented without explicit override,
          the operation is rejected to prevent fraudulent/corrupted stitching.
        """
        self._ensure_tenant(tenant_id)
        now = timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        normalized_email = self.normalize_email(verified_email)
        tenant_identities = self._identities_by_anon[tenant_id]
        tenant_emails = self._identities_by_email[tenant_id]

        # Case 1: Consent is Denied
        if consent_status.upper() in ("DENIED", "REVOKED", "OPT_OUT"):
            record = tenant_identities.get(anonymous_id)
            if not record:
                record = IdentityRecord(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    anonymous_id=anonymous_id,
                    status=IdentityStatus.CONSENT_DENIED,
                    is_matched=False,
                    unmatched_reason=UnmatchedReason.CONSENT_DENIED.value,
                    consent_status="DENIED",
                    first_seen_at=now,
                    last_seen_at=now,
                    metadata=metadata or {},
                )
                tenant_identities[anonymous_id] = record
            else:
                record.status = IdentityStatus.CONSENT_DENIED
                record.is_matched = False
                record.unmatched_reason = UnmatchedReason.CONSENT_DENIED.value
                record.consent_status = "DENIED"
                record.last_seen_at = now

            return IdentityResolutionResult(
                record=record,
                action="CONSENT_BLOCKED",
                success=True,
                message="User consent denied. Identity resolution and binding suppressed.",
            )

        # Check existing record for this anonymous ID
        existing = tenant_identities.get(anonymous_id)

        # Case 2: No verified identifier provided
        if not normalized_email and not phone_hash and not crm_contact_id:
            if existing:
                existing.last_seen_at = now
                if metadata:
                    existing.metadata.update(metadata)
                return IdentityResolutionResult(
                    record=existing,
                    action="RETAINED_UNMATCHED" if not existing.is_matched else "RETAINED_MATCHED",
                    success=True,
                    message="Existing identity retrieved without new identifiers.",
                )

            record = IdentityRecord(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                anonymous_id=anonymous_id,
                status=IdentityStatus.UNMATCHED,
                is_matched=False,
                unmatched_reason=UnmatchedReason.NO_VERIFIED_IDENTIFIER.value,
                consent_status="GRANTED",
                confidence_score=0.0,
                first_seen_at=now,
                last_seen_at=now,
                metadata=metadata or {},
            )
            tenant_identities[anonymous_id] = record
            return IdentityResolutionResult(
                record=record,
                action="CREATED",
                success=True,
                message="Anonymous identity created with status UNMATCHED.",
            )

        # Case 3: Verified identifier provided
        match_key = "email" if normalized_email else ("crm_contact_id" if crm_contact_id else "phone_hash")
        confidence = 1.0 if (normalized_email or crm_contact_id) else 0.95

        # Check for conflict: Does this anonymous ID already have a different verified email?
        if existing and existing.is_matched and existing.verified_email:
            if normalized_email and existing.verified_email != normalized_email and not force_link:
                return IdentityResolutionResult(
                    record=existing,
                    action="CONFLICT_PRESERVED",
                    success=False,
                    message=(
                        f"Identity conflict: anonymous_id '{anonymous_id}' is already bound to "
                        f"'{existing.verified_email}'. Cannot rebind to '{normalized_email}' without explicit authorization."
                    ),
                )

        # Check if the verified email already belongs to a known primary identity record
        primary_record: Optional[IdentityRecord] = None
        if normalized_email and normalized_email in tenant_emails:
            primary_id = tenant_emails[normalized_email]
            for rec in tenant_identities.values():
                if rec.id == primary_id:
                    primary_record = rec
                    break

        if primary_record:
            # Bind this anonymous_id to the existing primary identity
            primary_record.linked_anonymous_ids.add(anonymous_id)
            primary_record.last_seen_at = now
            if crm_contact_id and not primary_record.crm_contact_id:
                primary_record.crm_contact_id = crm_contact_id
            if phone_hash and not primary_record.phone_hash:
                primary_record.phone_hash = phone_hash
            if metadata:
                primary_record.metadata.update(metadata)
            tenant_identities[anonymous_id] = primary_record

            return IdentityResolutionResult(
                record=primary_record,
                action="LINKED",
                success=True,
                message=f"Anonymous ID '{anonymous_id}' bound to existing verified identity for '{normalized_email}'.",
            )

        # Build or upgrade the record to MATCHED
        record_id = existing.id if existing else str(uuid.uuid4())
        record = IdentityRecord(
            id=record_id,
            tenant_id=tenant_id,
            anonymous_id=anonymous_id,
            verified_email=normalized_email,
            phone_hash=phone_hash,
            crm_contact_id=crm_contact_id,
            confidence_score=confidence,
            match_key=match_key,
            status=IdentityStatus.MATCHED,
            is_matched=True,
            unmatched_reason=None,
            consent_status="GRANTED",
            first_seen_at=existing.first_seen_at if existing else now,
            last_seen_at=now,
            linked_anonymous_ids=existing.linked_anonymous_ids if existing else {anonymous_id},
            metadata=metadata or (existing.metadata if existing else {}),
        )

        tenant_identities[anonymous_id] = record
        if normalized_email:
            tenant_emails[normalized_email] = record.id

        return IdentityResolutionResult(
            record=record,
            action="LINKED" if existing else "CREATED",
            success=True,
            message="Identity successfully bound to verified credentials with 100% confidence.",
        )

    def record_touchpoint(self, touchpoint: Touchpoint) -> Tuple[Touchpoint, IdentityRecord]:
        """
        Ingests and records an immutable touchpoint, maintaining tenant boundary.
        Automatically checks and provisions the visitor identity record.
        """
        self._ensure_tenant(touchpoint.tenant_id)
        self._touchpoints[touchpoint.tenant_id].append(touchpoint)

        res = self.resolve_or_create(
            tenant_id=touchpoint.tenant_id,
            anonymous_id=touchpoint.visitor_id,
            consent_status=touchpoint.consent_status,
            timestamp=touchpoint.timestamp,
        )
        return touchpoint, res.record

    def get_identity(self, tenant_id: str, anonymous_id: str) -> Optional[IdentityRecord]:
        """Lookup identity record strictly scoped by tenant."""
        self._ensure_tenant(tenant_id)
        return self._identities_by_anon[tenant_id].get(anonymous_id)

    def get_identity_by_email(self, tenant_id: str, email: str) -> Optional[IdentityRecord]:
        """Lookup verified identity strictly scoped by tenant."""
        self._ensure_tenant(tenant_id)
        norm = self.normalize_email(email)
        if not norm or norm not in self._identities_by_email[tenant_id]:
            return None
        rec_id = self._identities_by_email[tenant_id][norm]
        for rec in self._identities_by_anon[tenant_id].values():
            if rec.id == rec_id:
                return rec
        return None

    def get_touchpoints(
        self, tenant_id: str, visitor_id: Optional[str] = None
    ) -> List[Touchpoint]:
        """Retrieve touchpoints for a tenant, optionally filtered by visitor_id."""
        self._ensure_tenant(tenant_id)
        tps = self._touchpoints[tenant_id]
        if visitor_id:
            return [tp for tp in tps if tp.visitor_id == visitor_id]
        return list(tps)

    @classmethod
    def from_tracking_payload(cls, payload: Dict[str, Any]) -> Touchpoint:
        """
        Constructs a validated Touchpoint object from a client-side tracking beacon payload.
        """
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            raise ValueError("Payload missing mandatory 'tenant_id'.")

        anonymous_id = payload.get("anonymous_id")
        if not anonymous_id:
            raise ValueError("Payload missing mandatory 'anonymous_id'.")

        ts_raw = payload.get("timestamp")
        if ts_raw:
            try:
                if isinstance(ts_raw, str):
                    timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                else:
                    timestamp = datetime.now(timezone.utc)
            except Exception:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        click_ids = payload.get("click_ids") or {}
        primary_click_id = payload.get("click_id")
        if not primary_click_id and isinstance(click_ids, dict):
            for k in ("gclid", "fbclid", "msclkid", "ttclid"):
                if click_ids.get(k):
                    primary_click_id = click_ids[k]
                    break

        return Touchpoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            visitor_id=anonymous_id,
            session_id=payload.get("session_id"),
            utm_source=payload.get("utm_source"),
            utm_medium=payload.get("utm_medium"),
            utm_campaign=payload.get("utm_campaign"),
            utm_content=payload.get("utm_content"),
            utm_term=payload.get("utm_term"),
            click_id=primary_click_id,
            click_ids=click_ids if isinstance(click_ids, dict) else {},
            url=payload.get("url"),
            referrer=payload.get("referrer"),
            ad_id=payload.get("ad_id"),
            timestamp=timestamp,
            consent_status=payload.get("consent_status", "GRANTED"),
            raw_payload=payload,
        )

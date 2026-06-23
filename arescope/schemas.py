"""Pipeline data units (pydantic) and the controlled vocabularies.

Flow:  Signal (raw, per-source)  ->  Evidence (normalized + deduped)
       ->  Finding (judged: category + severity)  ->  Remediation (fix plan).

These are the in-memory/transport shapes. Persistence shapes live in db/models.py;
they mirror these but add ids/fks/timestamps.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class InputType(str, enum.Enum):
    NAME = "name"
    USERNAME = "username"
    EMAIL = "email"
    PHOTO = "photo"
    IP = "ip"
    PHONE = "phone"


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Category(str, enum.Enum):
    """The finding taxonomy (FINDINGS_TAXONOMY.md §Category)."""

    CREDENTIAL_EXPOSURE = "credential_exposure"        # 1
    INFOSTEALER_INFECTION = "infostealer_infection"    # 2
    BREACH_MEMBERSHIP = "breach_membership"            # 3
    ACCOUNT_FOOTPRINT = "account_footprint"            # 4
    ACCOUNT_METADATA = "account_metadata"              # 5
    EXPOSED_INFRASTRUCTURE = "exposed_infrastructure"  # 6
    DATA_BROKER_LISTING = "data_broker_listing"        # 7
    USERNAME_CORRELATION = "username_correlation"      # 8
    FACE_PHOTO_EXPOSURE = "face_photo_exposure"        # 9


class RemediationTier(str, enum.Enum):
    T0_GUIDANCE = "t0_guidance"      # exact steps + deep links
    T1_ARTIFACT = "t1_artifact"      # auto-drafted opt-out / GDPR request
    T2_ASSISTED = "t2_assisted"      # pre-filled forms (P2)
    T3_AUTOMATED = "t3_automated"    # submitted on user's behalf (P2+, brokers only)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Identifier(BaseModel):
    """An input the operator owns/asserts ownership of."""

    type: InputType
    value: str
    ownership_verified: bool = False  # always True in P0 (asserted); gate flips in P2


class Signal(BaseModel):
    """Normalized pre-judgement unit emitted by a connector (TOOLS.md)."""

    source: str                          # connector name, e.g. "hibp"
    kind: str                            # source-specific, e.g. "breach", "stealer_log"
    locator: str                         # what it points at, e.g. breach name / site / port
    subject_value: str                   # the identifier value this concerns
    subject_type: InputType
    raw: dict = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=_now)


class Evidence(BaseModel):
    """A deduped cluster of Signals about one (subject, kind, locator)."""

    subject_value: str
    subject_type: InputType
    kind: str
    locator: str
    sources: list[str]                   # which connectors contributed
    signals: list[Signal]


class ActionBucket(str, enum.Enum):
    FIX_NOW = "fix_now"            # dangerous regardless of context
    WORTH_FIXING = "worth_fixing"  # should probably act; minor context dependence
    DEPENDS = "depends"            # severity hinges on answers to questions
    NO_ACTION = "no_action"        # info/low; rolled up in the report


class FixDifficulty(str, enum.Enum):
    EASY = "easy"          # universally known fix; shown inline, no extra LLM call
    INVOLVED = "involved"  # tailored fix / artifact, generated on demand


class Resolution(BaseModel):
    """One branch of a contingency question — precomputed so resolution is free."""

    severity: Severity
    action: ActionBucket
    note: str = ""


class ContingencyQuestion(BaseModel):
    """A yes/no factor the verdict depends on, with both branches precomputed."""

    prompt: str
    if_yes: Resolution
    if_no: Resolution


class EvidenceCluster(BaseModel):
    """Tier-0 grouping: similar evidence collapsed into one unit to judge.

    Bounds Opus cost (250 old breaches -> one cluster) and improves the report
    (one "you're in N breaches" finding, not N walls of text).
    """

    signature: str
    category_hint: Category
    subject_value: str
    subject_type: InputType
    kind: str
    members: list[Evidence]
    member_locators: list[str]
    force_escalate: bool = False
    escalate_reason: str | None = None


class Verdict(BaseModel):
    """The judge's structured verdict on a cluster (the schema Opus fills)."""

    category: Category
    severity: Severity
    action: ActionBucket
    title: str
    problem: str = ""    # one-line statement of the issue (what's exposed / the risk)
    rationale: str       # what it means + why it matters (the explanation)
    confidence: float
    fix_difficulty: FixDifficulty | None = None  # set for fix_now / worth_fixing
    easy_fix: str | None = None                   # inline one-liner when difficulty == easy
    questions: list[ContingencyQuestion] = Field(default_factory=list)  # only when depends


class RemediationStep(BaseModel):
    action: str
    detail: str
    link: str | None = None


class Remediation(BaseModel):
    tier: RemediationTier
    summary: str
    steps: list[RemediationStep] = Field(default_factory=list)
    artifact: str | None = None          # generated email / request text (T1)


class JudgedFinding(BaseModel):
    """A verdict bound to its evidence cluster + (optional, on-demand) remediation."""

    verdict: Verdict
    cluster: EvidenceCluster
    remediation: Remediation | None = None  # involved fix, generated on demand


class CoverageGap(BaseModel):
    """A source that didn't run / was blocked — surfaced honestly in the report."""

    source: str
    reason: str                          # e.g. "no API key", "rate-limited (429)"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

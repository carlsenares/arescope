"""The findings taxonomy as data (FINDINGS_TAXONOMY.md).

Two consumers:
  1. The judge — this is injected (cached) into the system prompt so the LLM
     classifies into a fixed vocabulary with consistent severity logic.
  2. The remediation engine — `default_tier` picks the fix track per category.

Keeping it as data (not prose in a prompt string) means the rubric is testable
and the judge + remediation stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

from aresis.schemas import Category, RemediationTier


@dataclass(frozen=True)
class CategorySpec:
    category: Category
    label: str
    surfaced_by: tuple[str, ...]
    meaning: str
    severity_logic: str
    default_tier: RemediationTier


TAXONOMY: dict[Category, CategorySpec] = {
    Category.CREDENTIAL_EXPOSURE: CategorySpec(
        category=Category.CREDENTIAL_EXPOSURE,
        label="Credential exposure",
        surfaced_by=("hibp", "dehashed"),
        meaning="Email/password appears in a breach corpus; password may be plaintext or a crackable hash.",
        severity_logic=(
            "Critical if plaintext + recent, or password reused on important accounts; "
            "High if hash/cracked; Low if old and already rotated."
        ),
        default_tier=RemediationTier.T1_ARTIFACT,
    ),
    Category.INFOSTEALER_INFECTION: CategorySpec(
        category=Category.INFOSTEALER_INFECTION,
        label="Infostealer infection",
        surfaced_by=("hudsonrock",),
        meaning="The user's device was infected; credentials + session cookies + autofill were exfiltrated.",
        severity_logic="Always Critical — implies live session theft and mass credential loss.",
        default_tier=RemediationTier.T0_GUIDANCE,
    ),
    Category.BREACH_MEMBERSHIP: CategorySpec(
        category=Category.BREACH_MEMBERSHIP,
        label="Breach membership",
        surfaced_by=("hibp",),
        meaning="Email is in breach(es); exposed data types vary (password, address, phone, DOB).",
        severity_logic="Scales with data type: password->High, address/phone->Medium, email-only->Low.",
        default_tier=RemediationTier.T1_ARTIFACT,
    ),
    Category.ACCOUNT_FOOTPRINT: CategorySpec(
        category=Category.ACCOUNT_FOOTPRINT,
        label="Account footprint",
        surfaced_by=("holehe", "maigret"),
        meaning="Which sites an email/username is registered on (often without alerting the target).",
        severity_logic=(
            "Medium (enables targeted phishing + deanonymization); higher if it links a "
            "'private' identity to a real-name one."
        ),
        default_tier=RemediationTier.T1_ARTIFACT,
    ),
    Category.ACCOUNT_METADATA: CategorySpec(
        category=Category.ACCOUNT_METADATA,
        label="Account/identity metadata",
        surfaced_by=("ghunt", "epieos"),
        meaning="Public Google/account data: display name, photo, linked services, public reviews/Maps.",
        severity_logic="Low-Medium (deanonymization, social-engineering fuel).",
        default_tier=RemediationTier.T0_GUIDANCE,
    ),
    Category.EXPOSED_INFRASTRUCTURE: CategorySpec(
        category=Category.EXPOSED_INFRASTRUCTURE,
        label="Exposed infrastructure",
        surfaced_by=("shodan", "censys"),
        meaning="Open ports / exposed services on an IP the user owns (RDP, DBs, cameras, NAS), plus CVEs.",
        severity_logic=(
            "Critical if default-cred/known-CVE admin service is reachable; High for any "
            "exposed sensitive service; Medium for informational banners."
        ),
        default_tier=RemediationTier.T0_GUIDANCE,
    ),
    Category.DATA_BROKER_LISTING: CategorySpec(
        category=Category.DATA_BROKER_LISTING,
        label="Data-broker / people-search listing",
        surfaced_by=("brokers",),
        meaning="Home address, phone, relatives, age listed on broker/aggregator sites.",
        severity_logic="High if home address is public (doxxing/swatting risk); Medium otherwise.",
        default_tier=RemediationTier.T1_ARTIFACT,
    ),
    Category.USERNAME_CORRELATION: CategorySpec(
        category=Category.USERNAME_CORRELATION,
        label="Username correlation",
        surfaced_by=("maigret", "sherlock"),
        meaning="The same username across many platforms lets anyone correlate activity into one profile.",
        severity_logic="Low-Medium (deanonymization).",
        default_tier=RemediationTier.T0_GUIDANCE,
    ),
    Category.FACE_PHOTO_EXPOSURE: CategorySpec(
        category=Category.FACE_PHOTO_EXPOSURE,
        label="Face / photo exposure",
        surfaced_by=("pimeyes",),
        meaning="A photo of the user appears on other sites/profiles.",
        severity_logic="Medium-High (stalking, deanonymization, impersonation).",
        default_tier=RemediationTier.T1_ARTIFACT,
    ),
}


def taxonomy_prompt_block() -> str:
    """Render the rubric for injection into the (cached) judge system prompt."""
    lines = [
        "FINDING CATEGORIES (classify each evidence item into exactly one):",
        "",
    ]
    for spec in TAXONOMY.values():
        lines.append(f"- {spec.category.value} ({spec.label})")
        lines.append(f"    meaning: {spec.meaning}")
        lines.append(f"    severity: {spec.severity_logic}")
    return "\n".join(lines)

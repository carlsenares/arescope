"""Report builder — severity-sorted JSON + rendered Markdown.

The report must never imply coverage it didn't have (ARCHITECTURE.md §4.5), so
coverage gaps are first-class and rendered explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from aresis.schemas import SEVERITY_ORDER, CoverageGap, JudgedFinding, Severity


class ScanReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    findings: list[JudgedFinding] = Field(default_factory=list)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)

    @property
    def sorted_findings(self) -> list[JudgedFinding]:
        return sorted(
            self.findings,
            key=lambda jf: SEVERITY_ORDER[jf.finding.severity],
            reverse=True,
        )

    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for jf in self.findings:
            counts[jf.finding.severity.value] += 1
        return counts


def render_markdown(report: ScanReport) -> str:
    lines: list[str] = ["# Aresis exposure report", ""]
    lines.append(f"_Generated {report.generated_at:%Y-%m-%d %H:%M UTC}_")
    lines.append("")

    counts = report.severity_counts()
    summary = " · ".join(
        f"{counts[s.value]} {s.value}" for s in Severity if counts[s.value]
    )
    lines.append(f"**Summary:** {summary or 'no findings'}")
    lines.append("")

    for jf in report.sorted_findings:
        f = jf.finding
        lines.append(f"## [{f.severity.value.upper()}] {f.title}")
        lines.append("")
        lines.append(f"- **Category:** {f.category.value}")
        lines.append(f"- **Confidence:** {f.confidence:.0%}")
        lines.append(
            f"- **Where:** {jf.evidence.locator} "
            f"(via {', '.join(jf.evidence.sources)})"
        )
        lines.append("")
        lines.append(f.rationale)
        lines.append("")
        if jf.remediation:
            r = jf.remediation
            lines.append(f"**Fix ({r.tier.value}):** {r.summary}")
            lines.append("")
            for i, step in enumerate(r.steps, 1):
                link = f" — {step.link}" if step.link else ""
                lines.append(f"{i}. **{step.action}** — {step.detail}{link}")
            if r.artifact:
                lines.append("")
                lines.append("<details><summary>Generated request (ready to send)</summary>")
                lines.append("")
                lines.append("```")
                lines.append(r.artifact)
                lines.append("```")
                lines.append("")
                lines.append("</details>")
            lines.append("")

    if report.coverage_gaps:
        lines.append("## Coverage gaps")
        lines.append("")
        lines.append("_These sources did not run; the scan above does not cover them._")
        lines.append("")
        for gap in report.coverage_gaps:
            lines.append(f"- **{gap.source}** — {gap.reason}")
        lines.append("")

    return "\n".join(lines)

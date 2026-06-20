"""Report builder — grouped by action bucket, severity-sorted, with a rolled-up tail.

Layout follows AI_PIPELINE.md §Display: Fix now / Worth fixing (easy fix inline,
involved shown as a generate affordance) -> Depends (with questions) -> the
low/no-action tail collapsed. Coverage gaps are first-class — the report never
implies coverage it didn't have.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from arescope.schemas import (
    SEVERITY_ORDER,
    ActionBucket,
    CoverageGap,
    FixDifficulty,
    JudgedFinding,
    Severity,
)


class ScanReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    findings: list[JudgedFinding] = Field(default_factory=list)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)

    def by_action(self, action: ActionBucket) -> list[JudgedFinding]:
        items = [jf for jf in self.findings if jf.verdict.action is action]
        return sorted(items, key=lambda jf: SEVERITY_ORDER[jf.verdict.severity], reverse=True)

    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for jf in self.findings:
            counts[jf.verdict.severity.value] += 1
        return counts


def _render_finding(jf: JudgedFinding) -> list[str]:
    v, c = jf.verdict, jf.cluster
    lines = [f"### [{v.severity.value.upper()}] {v.title}", ""]
    lines.append(f"- **Category:** {v.category.value}")
    lines.append(f"- **Confidence:** {v.confidence:.0%}")
    where = ", ".join(c.member_locators[:8])
    if len(c.member_locators) > 8:
        where += f", +{len(c.member_locators) - 8} more"
    lines.append(f"- **Where:** {where or c.kind} (via {', '.join(sorted({s for e in c.members for s in e.sources}))})")
    lines.append("")
    lines.append(v.rationale)
    lines.append("")

    if v.easy_fix:
        lines.append(f"**Fix (easy):** {v.easy_fix}")
        lines.append("")
    elif v.fix_difficulty is FixDifficulty.INVOLVED and not jf.remediation:
        lines.append("**Fix:** a tailored plan + ready-to-send request can be generated for this finding.")
        lines.append("")

    if jf.remediation:
        r = jf.remediation
        lines.append(f"**Fix ({r.tier.value}):** {r.summary}")
        lines.append("")
        for i, step in enumerate(r.steps, 1):
            link = f" — {step.link}" if step.link else ""
            lines.append(f"{i}. **{step.action}** — {step.detail}{link}")
        if r.artifact:
            lines += ["", "<details><summary>Generated request (ready to send)</summary>", "", "```", r.artifact, "```", "", "</details>"]
        lines.append("")
    return lines


def _render_questions(jf: JudgedFinding) -> list[str]:
    v, c = jf.verdict, jf.cluster
    where = ", ".join(c.member_locators[:8])
    lines = [f"### [depends] {v.title}", "", f"- **Where:** {where or c.kind}", "", v.rationale, ""]
    lines.append("**To pin down the severity, answer:**")
    lines.append("")
    for q in v.questions:
        lines.append(f"- [ ] {q.prompt}")
        lines.append(f"      - yes → {q.if_yes.severity.value}: {q.if_yes.note}")
        lines.append(f"      - no → {q.if_no.severity.value}: {q.if_no.note}")
    lines.append("")
    return lines


def render_markdown(report: ScanReport) -> str:
    out: list[str] = ["# Arescope exposure report", "", f"_Generated {report.generated_at:%Y-%m-%d %H:%M UTC}_", ""]

    counts = report.severity_counts()
    summary = " · ".join(f"{counts[s.value]} {s.value}" for s in Severity if counts[s.value])
    out += [f"**Summary:** {summary or 'no findings'}", ""]

    fix_now = report.by_action(ActionBucket.FIX_NOW)
    worth = report.by_action(ActionBucket.WORTH_FIXING)
    depends = report.by_action(ActionBucket.DEPENDS)
    tail = report.by_action(ActionBucket.NO_ACTION)

    if fix_now:
        out += ["## Fix now", ""]
        for jf in fix_now:
            out += _render_finding(jf)
    if worth:
        out += ["## Worth fixing", ""]
        for jf in worth:
            out += _render_finding(jf)
    if depends:
        out += ["## Depends on your circumstances", ""]
        for jf in depends:
            out += _render_questions(jf)

    if tail:
        out += ["## Lower-risk footprint", "", "_Rolled up — review if you want, or solve any of them on demand._", ""]
        for jf in tail:
            n = len(jf.cluster.members)
            extra = f" ({n} items)" if n > 1 else ""
            out.append(f"- **[{jf.verdict.severity.value}]** {jf.verdict.title}{extra} — {jf.verdict.rationale}")
        out.append("")

    if report.coverage_gaps:
        out += ["## Coverage gaps", "", "_These sources did not run; the scan above does not cover them._", ""]
        for gap in report.coverage_gaps:
            out.append(f"- **{gap.source}** — {gap.reason}")
        out.append("")

    return "\n".join(out)

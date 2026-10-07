"""Researcher metrics (Perfect 6 #6, supporting the R1 KPI row).

GET /metrics — coverage + quality KPIs for the researcher dashboard.

North-star (PRD): coverage freshness — the share of OAH sites that are fresh
(need < 0.3). Counts are computed live from the seeded sites and submitted
observations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.experiment import MIN_PER_ARM, VERIFY_LIFT_EXPERIMENT
from app.models.observation import Observation
from app.models.site import Site
from app.models.verify import VerifyItem, Vote

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsOut(BaseModel):
    sites_total: int
    sites_needing_attention: int
    verified_this_month: int
    open_expert_reviews: int
    coverage_fresh_pct: int
    # --- Honest secondary metrics: each carries its sample size so nothing is
    # overclaimed. null when there isn't enough data yet (don't fabricate). ---
    # How often the AI's visual suggestion matched the community's decision.
    ai_human_agreement_pct: int | None = None
    ai_human_agreement_n: int = 0
    # Median seconds a verifier spent on a card (NOT a lift — there is no
    # human-only control group; see roadmap).
    median_verify_seconds: float | None = None
    verify_votes_n: int = 0
    # Share of recently-checked sites that got ≥2 checks in 30 days.
    revisit_rate_pct: int | None = None
    revisit_eligible_n: int = 0
    # KPIs are computed live from real OAH sites + submitted observations; only
    # the per-site "last check" schedule is illustrative (see SiteOut.recency_simulated).
    simulated: bool = False


class ArmStats(BaseModel):
    n: int = 0  # total votes in this arm
    gold_n: int = 0  # votes on gold items (ground truth known)
    gold_accuracy_pct: int | None = None  # share correct vs gold_answer
    median_seconds: float | None = None


class VerificationLiftOut(BaseModel):
    """AI-assisted vs human-only verification lift (experimental, not validated).

    Gold items carry a known answer, so per-arm accuracy is measurable. ``status``
    is ``insufficient_data`` until BOTH arms reach ``min_per_arm`` gold votes; the
    lift is reported only then, and still labelled experimental — never presented
    as a statistically significant measurement (PRD/roadmap).
    """

    experiment: str
    status: str  # insufficient_data | ready
    min_per_arm: int
    assisted: ArmStats
    control: ArmStats
    accuracy_lift_pct: int | None = None  # assisted − control, only when ready
    note: str


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar() or 0)


def _median(xs: list[int]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[len(xs) // 2] / 1000.0, 1)


@router.get("", response_model=MetricsOut)
async def metrics(session: AsyncSession = Depends(get_session)) -> MetricsOut:
    sites_total = await _count(session, select(func.count(Site.id)))
    # "Needs attention" = need score in the amber/urgent bands (>= 0.3).
    needing = await _count(
        session, select(func.count(Site.id)).where(Site.need_score >= 0.3)
    )
    fresh = await _count(
        session, select(func.count(Site.id)).where(Site.need_score < 0.3)
    )
    verified = await _count(
        session,
        select(func.count(Observation.id)).where(
            Observation.status.in_(("community-verified", "final"))
        ),
    )
    open_expert = await _count(
        session, select(func.count(Observation.id)).where(Observation.status == "expert")
    )
    coverage = round(100 * fresh / sites_total) if sites_total else 0

    # --- AI–Human agreement: does the AI's prior match the community decision? ---
    # Per resolved item with an AI signal, community decision = majority of
    # decisive votes (yes = agrees with submitter). Compare to item.ai_agrees.
    vote_rows = (
        await session.execute(
            select(Vote.verify_item_id, Vote.answer).where(Vote.answer.in_(("yes", "no")))
        )
    ).all()
    yes_no: dict[int, list[int]] = {}
    for item_id, answer in vote_rows:
        y, n = yes_no.setdefault(item_id, [0, 0])
        if answer == "yes":
            yes_no[item_id] = [y + 1, n]
        else:
            yes_no[item_id] = [y, n + 1]
    ai_items = (
        await session.execute(
            select(VerifyItem.id, VerifyItem.ai_agrees).where(
                VerifyItem.resolved.is_(True), VerifyItem.ai_agrees.is_not(None)
            )
        )
    ).all()
    matches = comparable = 0
    for item_id, ai_agrees in ai_items:
        counts = yes_no.get(item_id)
        if not counts or counts[0] == counts[1]:
            continue  # no decisive majority → skip
        community = counts[0] > counts[1]
        comparable += 1
        if community == bool(ai_agrees):
            matches += 1
    agreement_pct = round(100 * matches / comparable) if comparable else None

    # --- Median verifier time (NOT a lift; no human-only control group) ---
    times = [
        int(t)
        for (t,) in (
            await session.execute(
                select(Vote.ms_taken).where(
                    Vote.ms_taken.is_not(None), Vote.answer.in_(("yes", "no"))
                )
            )
        ).all()
    ]
    if times:
        times.sort()
        median_ms = times[len(times) // 2]
        median_s: float | None = round(median_ms / 1000.0, 1)
    else:
        median_s = None

    # --- Revisit rate: sites with ≥2 checks in 30 days / sites checked at all ---
    since = datetime.now(UTC) - timedelta(days=30)
    per_site = (
        await session.execute(
            select(Observation.site_id, func.count(Observation.id))
            .where(Observation.created_at >= since, Observation.site_id.is_not(None))
            .group_by(Observation.site_id)
        )
    ).all()
    eligible = len(per_site)
    revisited = sum(1 for _, c in per_site if c >= 2)
    revisit_pct = round(100 * revisited / eligible) if eligible else None

    return MetricsOut(
        sites_total=sites_total,
        sites_needing_attention=needing,
        verified_this_month=verified,
        open_expert_reviews=open_expert,
        coverage_fresh_pct=coverage,
        ai_human_agreement_pct=agreement_pct,
        ai_human_agreement_n=comparable,
        median_verify_seconds=median_s,
        verify_votes_n=len(times),
        revisit_rate_pct=revisit_pct,
        revisit_eligible_n=eligible,
    )


@router.get("/experiment/verification-lift", response_model=VerificationLiftOut)
async def verification_lift(
    session: AsyncSession = Depends(get_session),
) -> VerificationLiftOut:
    """AI-assisted vs human-only verification lift (see app/experiment.py).

    Measures, per arm, accuracy on gold items (known answer) and median decision
    time. Honestly gated: reports a lift only once both arms clear ``min_per_arm``
    gold votes, and always labels the result experimental.
    """
    # Votes with an arm, joined to their item's gold answer (when gold).
    rows = (
        await session.execute(
            select(Vote.arm, Vote.answer, Vote.ms_taken, VerifyItem.is_gold, VerifyItem.gold_answer)
            .join(VerifyItem, Vote.verify_item_id == VerifyItem.id)
            .where(Vote.arm.is_not(None))
        )
    ).all()

    stats: dict[str, dict] = {
        "assisted": {"n": 0, "gold_n": 0, "correct": 0, "times": []},
        "control": {"n": 0, "gold_n": 0, "correct": 0, "times": []},
    }
    for arm, answer, ms_taken, is_gold, gold_answer in rows:
        s = stats.get(arm)
        if s is None:
            continue
        s["n"] += 1
        if ms_taken is not None and answer in ("yes", "no"):
            s["times"].append(int(ms_taken))
        if is_gold and gold_answer is not None:
            s["gold_n"] += 1
            if answer == gold_answer:
                s["correct"] += 1

    def _arm(name: str) -> ArmStats:
        s = stats[name]
        acc = round(100 * s["correct"] / s["gold_n"]) if s["gold_n"] else None
        return ArmStats(
            n=s["n"], gold_n=s["gold_n"], gold_accuracy_pct=acc, median_seconds=_median(s["times"])
        )

    assisted, control = _arm("assisted"), _arm("control")
    ready = assisted.gold_n >= MIN_PER_ARM and control.gold_n >= MIN_PER_ARM
    lift = (
        assisted.gold_accuracy_pct - control.gold_accuracy_pct
        if ready
        and assisted.gold_accuracy_pct is not None
        and control.gold_accuracy_pct is not None
        else None
    )
    return VerificationLiftOut(
        experiment=VERIFY_LIFT_EXPERIMENT,
        status="ready" if ready else "insufficient_data",
        min_per_arm=MIN_PER_ARM,
        assisted=assisted,
        control=control,
        accuracy_lift_pct=lift,
        note=(
            "Experimental: AI-assisted vs human-only verification. "
            "Not a statistically validated measurement."
        ),
    )

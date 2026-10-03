"""Verification trust recompute — turns votes into observation trust + state.

Kept out of the router so it can be unit/integration tested directly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scoring
from app.models.observation import Observation
from app.models.verify import VerifyItem, Vote

# Default verifier reliability by kind until per-voter Beta posteriors are
# persisted (PRD reliability table — TODO). Crew-mates are down-weighted.
R_BY_KIND = {"keeper": 0.75, "member": 0.6, "researcher": 0.85}


def _is_split(yes: int, no: int) -> bool:
    total = yes + no
    return total >= 3 and 0.4 <= yes / total <= 0.6


async def recompute_trust(session: AsyncSession, observation_id: int) -> tuple[float, str, int]:
    """Recompute and persist trust + state for one observation.

    Returns ``(trust, status, total_decisive_votes)``.
    """
    obs = await session.get(Observation, observation_id)
    if obs is None:
        return (0.0, "unknown", 0)

    items = (
        await session.execute(
            select(VerifyItem).where(VerifyItem.observation_id == observation_id)
        )
    ).scalars().all()

    field_trusts: list[float] = []
    total_votes = 0
    any_split = False

    for item in items:
        votes = (
            await session.execute(select(Vote).where(Vote.verify_item_id == item.id))
        ).scalars().all()
        decisive = [v for v in votes if v.answer in ("yes", "no")]
        total_votes += len(decisive)
        if not decisive:
            continue
        yes = sum(1 for v in decisive if v.answer == "yes")
        no = len(decisive) - yes
        any_split = any_split or _is_split(yes, no)
        vote_models = [
            scoring.Vote(
                reliability=R_BY_KIND.get(v.voter_kind, 0.7),
                agrees=(v.answer == "yes"),
                is_crewmate=(v.voter_kind == "member"),
            )
            for v in decisive
        ]
        field_trusts.append(
            scoring.field_trust(
                vote_models, ai_agrees=item.ai_agrees, ai_confidence=item.ai_confidence
            )
        )
        if len(votes) >= 3:
            item.resolved = True

    trust = scoring.observation_trust(field_trusts) if field_trusts else None

    if total_votes == 0:
        obs.status = "expert" if obs.pipe_flag else "in_verify"
    else:
        obs.status = scoring.verification_state(
            trust or 0.0,
            total_votes,
            any_field_split=any_split,
            pipe_or_sewage_flag=obs.pipe_flag,
        )
    obs.trust = trust
    return (trust or 0.0, obs.status, total_votes)

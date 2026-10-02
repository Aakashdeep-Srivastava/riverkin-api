"""Pydantic response models for the public API."""

from __future__ import annotations

from pydantic import BaseModel


class SiteOut(BaseModel):
    """A monitored OAH site with its current attention state.

    ``id`` is the stable OAH code (string) so the front end can route on it.
    """

    id: str
    name: str
    waterbody: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    days_unseen: int
    rain_48h_mm: float
    need_score: float
    attention: str
    color: str
    simulated: bool = True


class TimelineEntry(BaseModel):
    kind: str
    label: str
    at: str


class SiteTimelineOut(BaseModel):
    site_id: str
    entries: list[TimelineEntry]
    simulated: bool = True

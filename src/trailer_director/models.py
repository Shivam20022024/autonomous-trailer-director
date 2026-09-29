"""Pydantic schemas for the supplied episode package and for generated trailer plans."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .timecode import parse_tc


class DialogueLine(BaseModel):
    line_id: str
    speaker: str
    addressee: Optional[str] = None
    start: str
    end: str
    text: str

    @property
    def start_s(self) -> float:
        return parse_tc(self.start)

    @property
    def end_s(self) -> float:
        return parse_tc(self.end)


class Moment(BaseModel):
    moment_id: str
    start: str
    end: str
    description: str
    characters: list[str] = []
    visual_tags: list[str] = []

    @property
    def start_s(self) -> float:
        return parse_tc(self.start)

    @property
    def end_s(self) -> float:
        return parse_tc(self.end)


class Scene(BaseModel):
    scene_id: str
    title: str
    start_time: str
    end_time: str
    human_description: str
    ai_description: str = ""
    characters_present: list[str] = []
    tags: list[str] = []
    source_music: Optional[str] = None
    cultural_notes: Optional[str] = None
    dialogue: list[DialogueLine] = []
    moments: list[Moment] = []

    @property
    def start_s(self) -> float:
        return parse_tc(self.start_time)

    @property
    def end_s(self) -> float:
        return parse_tc(self.end_time)

    @model_validator(mode="after")
    def _items_inside_scene(self):
        s0, s1 = self.start_s, self.end_s
        if s1 <= s0:
            raise ValueError(f"{self.scene_id}: end_time must be after start_time")
        for item in [*self.dialogue, *self.moments]:
            if not (s0 <= item.start_s < item.end_s <= s1):
                ident = getattr(item, "line_id", None) or getattr(item, "moment_id")
                raise ValueError(f"{self.scene_id}: {ident} timecodes fall outside the scene")
        return self


class Character(BaseModel):
    character_id: str
    name: str
    description: str
    actor_id: str


class Episode(BaseModel):
    episode_id: str
    title: str
    duration: str
    source_language: str
    characters: list[Character]
    scenes: list[Scene]

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.scene_id for s in self.scenes]
        ids += [l.line_id for s in self.scenes for l in s.dialogue]
        ids += [m.moment_id for s in self.scenes for m in s.moments]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate ids in episode package: {sorted(dupes)}")
        return self


# ---- output schema -------------------------------------------------------

class TextCard(BaseModel):
    text: str
    seconds: float


class VoiceOver(BaseModel):
    text: str
    caption: Optional[str] = None


class SubtitleCue(BaseModel):
    line_id: str
    start: str
    end: str
    text: Optional[str]


class Subtitle(BaseModel):
    track: str
    text: str
    cues: list[SubtitleCue]


class Segment(BaseModel):
    segment_id: str
    order: int
    beat: str
    video: str
    source_ref: Optional[str]
    source_in: str
    source_out: str
    duration_seconds: Optional[float]
    audio: Literal["original_mix", "dialogue_and_music", "dialogue_only", "music_only"]
    music: Optional[str]
    dialogue: list[dict]
    subtitle: Optional[Subtitle]
    voice_over: Optional[VoiceOver] = None
    text_card: Optional[TextCard] = None
    transition: str
    reason: str
    evidence: list[str]
    depends_on: list[str]
    risk_flags: list[str]


class Validation(BaseModel):
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    errors: list[dict]
    warnings: list[dict]
    checks_run: list[str]


class TrailerPlan(BaseModel):
    trailer_id: str
    version: int
    audience: str
    audience_id: str
    market: str
    objective: str
    audience_promise: str
    emotional_journey: list[str]
    target_duration_seconds: list[float]
    duration_seconds: float
    music_plan: dict
    insights_used: list[str]
    segments: list[Segment]
    validation: Validation
    ready_for_editor: bool
    repair_history: list[dict]
    assumptions: list[str]
    human_approvals_required: list[dict]
    cost: dict
    planning_source: dict
    revisions: list[dict] = Field(default_factory=list)

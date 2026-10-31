"""Assign inspection identities only to repeated, current fish observations.

Native association IDs are private. ByteTrack consumes IDs for tentative tracks,
and its first update can activate a one-frame detection. Neither is evidence of
another inspected fish. This gate leaves detections visible without an identity
until the same associated fish is observed on consecutive frames.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from numbers import Integral
from time import monotonic

from src.api.domain import Detection, DetectionConfirmation


@dataclass
class _Identity:
    first: Detection
    first_seen: float
    last_frame: int
    last_association_frame: int
    observations: int = 1
    fish_id: int | None = None


class ConfirmedFishIdentities:
    """Keep short occlusions stable without allocating IDs for empty frames."""

    def __init__(self, minimum_observations: int = 2, max_missing_frames: int = 30) -> None:
        if isinstance(minimum_observations, bool) or not isinstance(minimum_observations, int) or minimum_observations < 2:
            raise ValueError("Fish identity confirmation requires at least two observed frames.")
        self.minimum_observations = minimum_observations
        self.max_missing_frames = max_missing_frames
        self.reset()

    def reset(self) -> None:
        self._states: dict[int, _Identity] = {}
        self._next_id = 1
        self._frame = 0
        self._native_high_water = 0
        self._last_candidates = 0
        self._last_tentative = 0

    def update(self, detections: list[Detection], *, minimum_confidence: float = 0.0,
               observed_tracks: list[Detection] | None = None,
               timestamp: float | None = None) -> list[Detection]:
        now = monotonic() if timestamp is None else timestamp
        self._frame += 1
        self._states = {key: state for key, state in self._states.items()
                        if self._frame - state.last_association_frame <= self.max_missing_frames + 1}

        def valid_observation(item: Detection) -> bool:
            return (item.class_id == 0 and item.class_name == "Fish"
                    and isfinite(item.confidence) and 0 <= item.confidence <= 1
                    and len(item.bbox) == 4 and all(isfinite(value) for value in item.bbox)
                    and item.bbox[2] > item.bbox[0] and item.bbox[3] > item.bbox[1])

        def native_id(item: Detection) -> int | None:
            if isinstance(item.track_id, Integral) and not isinstance(item.track_id, bool) and item.track_id >= 0:
                return int(item.track_id)
            return None

        valid = [item for item in detections if valid_observation(item) and item.confidence >= minimum_confidence]
        observed = valid if observed_tracks is None else [item for item in observed_tracks if valid_observation(item)]
        observation_counts: dict[int, int] = {}
        for item in observed:
            key = native_id(item)
            if key is not None:
                observation_counts[key] = observation_counts.get(key, 0) + 1
        for item in observed:
            key = native_id(item)
            if key is None or observation_counts[key] != 1:
                continue
            self._native_high_water = max(self._native_high_water, key)
            state = self._states.get(key)
            if item.confidence < minimum_confidence:
                # Weak CURRENT measurements can keep an established identity
                # alive indefinitely. Predictions and empty frames cannot.
                if state is not None and state.fish_id is not None:
                    state.last_association_frame = self._frame
                continue
            if state is None or (state.fish_id is None and state.last_frame != self._frame - 1):
                state = _Identity(item, now, self._frame, self._frame)
                self._states[key] = state
            else:
                state.observations += 1
                state.last_frame = self._frame
                state.last_association_frame = self._frame
        occurrences: dict[int, int] = {}
        for item in valid:
            key = native_id(item)
            if key is not None:
                occurrences[key] = occurrences.get(key, 0) + 1
        output = []
        self._last_candidates = self._last_tentative = 0
        for item in valid:
            key = native_id(item)
            if key is None or occurrences.get(key) != 1:
                output.append(replace(item, track_id=None, confirmation=None))
                continue
            self._last_candidates += 1
            state = self._states.get(key)
            if state is None or state.last_frame != self._frame:
                output.append(replace(item, track_id=None, confirmation=None))
                continue
            confirmation = None
            if state.fish_id is None and state.observations >= self.minimum_observations:
                state.fish_id = self._next_id
                self._next_id += 1
                # Keep the observed movement before confirmation so a fish
                # crossing the line on this very frame is still counted once.
                confirmation = DetectionConfirmation(state.first.bbox, state.first.confidence, state.first_seen)
            if state.fish_id is None:
                self._last_tentative += 1
            output.append(replace(item, track_id=state.fish_id, confirmation=confirmation))
        return output

    def diagnostics(self) -> dict[str, int]:
        return {
            "confirmation_frames": self.minimum_observations,
            "confirmed_fish_ids": self._next_id - 1,
            "native_id_high_water": self._native_high_water,
            "current_tracker_candidates": self._last_candidates,
            "current_tentative_candidates": self._last_tentative,
            "pending_candidates": sum(state.fish_id is None for state in self._states.values()),
        }

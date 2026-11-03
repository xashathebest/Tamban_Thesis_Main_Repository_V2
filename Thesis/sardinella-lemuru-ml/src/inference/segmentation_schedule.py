"""Latency-aware sampling decisions; never propagate masks between frames."""
from __future__ import annotations

from time import monotonic


class AdaptiveSegmentationSchedule:
    def __init__(self, *, minimum_frame_interval=3, refresh_frame_interval=15,
                 minimum_seconds=.5, refresh_seconds=5., latency_multiplier=2., clock=monotonic):
        self.minimum_frame_interval = max(1, int(minimum_frame_interval))
        self.refresh_frame_interval = max(self.minimum_frame_interval, int(refresh_frame_interval))
        self.minimum_seconds, self.refresh_seconds = max(0., minimum_seconds), max(.1, refresh_seconds)
        self.latency_multiplier, self.clock = max(1., latency_multiplier), clock
        self.reset()

    def reset(self):
        self.last = None
        self.last_frame = None
        self.last_finished = None
        self.next_allowed = 0.
        self.pending = None
        self.last_reason = "not_sampled"
        self.samples = self.deferred = 0
        self.last_segmentation_ms = 0.

    @staticmethod
    def signature(parents):
        rows = tuple(sorted((p.track_id, tuple(float(v) for v in p.bbox)) for p in parents))
        overlaps = []
        for index, (owner, box) in enumerate(rows):
            for other, second in rows[index + 1:]:
                if min(box[2], second[2]) > max(box[0], second[0]) and min(box[3], second[3]) > max(box[1], second[1]):
                    overlaps.append((owner, other))
        return rows, tuple(overlaps)

    def choose(self, parents, frame_number):
        signature = self.signature(parents)
        now = self.clock()
        if not signature[0]:
            self.last_reason = "no_fish"
            return "geometry_only"
        reason = None
        if self.last is None:
            reason = "first_sample"
        elif tuple(row[0] for row in signature[0]) != tuple(row[0] for row in self.last[0]):
            reason = "fish_identity_changed"
        elif signature[1] != self.last[1]:
            reason = "overlap_changed"
        elif any(max(abs(a-b) for a,b in zip(box, old)) > .025 * max(1., box[2]-box[0], box[3]-box[1])
                 for (_, box), (_, old) in zip(signature[0], self.last[0])):
            reason = "geometry_moved"
        elif frame_number - self.last_frame >= self.refresh_frame_interval or now - self.last_finished >= self.refresh_seconds:
            reason = "periodic_refresh"
        if reason is None:
            self.last_reason = "stable_geometry_waiting_for_refresh"
            self.deferred += 1
            return "geometry_only"
        if now < self.next_allowed or (self.last_frame is not None and frame_number - self.last_frame < self.minimum_frame_interval):
            self.last_reason = "deferred_for_latency_budget:" + reason
            self.deferred += 1
            return "geometry_only"
        self.pending = (signature, frame_number)
        self.last_reason = reason
        return "mobilesam_experimental"

    def record(self, segmentation_ms):
        if self.pending is None:
            return
        self.last, self.last_frame = self.pending
        self.pending = None
        self.last_finished = self.clock()
        self.last_segmentation_ms = max(0., float(segmentation_ms or 0.))
        self.next_allowed = self.last_finished + max(self.minimum_seconds, self.latency_multiplier*self.last_segmentation_ms/1000)
        self.samples += 1

    def diagnostics(self):
        return {"mode": "adaptive_identity_geometry_overlap_latency", "last_reason": self.last_reason,
                "samples": self.samples, "deferred_frames": self.deferred,
                "last_segmentation_ms": self.last_segmentation_ms,
                "minimum_frame_interval": self.minimum_frame_interval,
                "refresh_frame_interval": self.refresh_frame_interval,
                "latency_multiplier": self.latency_multiplier, "masks_reused_across_frames": False}

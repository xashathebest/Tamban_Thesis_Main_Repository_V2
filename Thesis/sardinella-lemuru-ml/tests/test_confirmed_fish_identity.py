"""Public fish IDs require real temporal evidence, independent of native IDs."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.api.camera import CameraInspectionService
from src.api.domain import Detection, InspectionState, TrackingConfig, TrackingManager
from src.inference.track_identity import ConfirmedFishIdentities


def fish(native_id=400, x=30, confidence=.9):
    return Detection(0, "Fish", confidence, (x, 10, x + 20, 30), native_id)


def test_hundreds_of_empty_or_single_frame_noise_updates_do_not_consume_fish_ids():
    identities = ConfirmedFishIdentities()
    for index in range(200):
        assert identities.update([fish(index)], timestamp=index * .1)[0].track_id is None
        assert identities.update([], timestamp=index * .1 + .05) == []
    assert identities.diagnostics()["confirmed_fish_ids"] == 0
    identities.update([fish(999)], timestamp=21)
    assert identities.update([fish(999)], timestamp=21.1)[0].track_id == 1


def test_first_byte_track_frame_requires_a_second_observed_detection():
    identities = ConfirmedFishIdentities()
    assert identities.update([fish()], timestamp=1)[0].track_id is None
    confirmed = identities.update([fish(x=45)], timestamp=1.1)[0]
    assert confirmed.track_id == 1
    assert confirmed.confirmation.bbox == fish().bbox
    assert confirmed.confirmation.timestamp == 1
    assert identities.update([fish(x=50)], timestamp=1.2)[0].track_id == 1


def test_tentative_detection_after_a_gap_must_confirm_again():
    identities = ConfirmedFishIdentities()
    identities.update([fish()], timestamp=0)
    identities.update([], timestamp=.1)
    assert identities.update([fish()], timestamp=.2)[0].track_id is None
    assert identities.update([fish()], timestamp=.3)[0].track_id == 1


def test_confirmed_fish_retains_identity_after_short_occlusion_without_predictions():
    identities = ConfirmedFishIdentities()
    identities.update([fish()], timestamp=0)
    identities.update([fish()], timestamp=.1)
    for index in range(5):
        assert identities.update([], timestamp=.2 + index / 10) == []
    returned = identities.update([fish(x=45)], timestamp=.8)[0]
    assert returned.track_id == 1
    assert returned.confirmation is None
    assert identities.diagnostics()["confirmed_fish_ids"] == 1


def test_duplicate_or_invalid_native_assignments_cannot_confirm_an_id():
    identities = ConfirmedFishIdentities()
    for _ in range(4):
        output = identities.update([fish(), fish(x=60), fish(-1), fish(None), fish(2.5)])
        assert all(item.track_id is None for item in output)
    assert identities.diagnostics()["confirmed_fish_ids"] == 0


@pytest.mark.parametrize("invalid", [
    replace(fish(), confidence=float("nan")), replace(fish(), confidence=1.1),
    replace(fish(), bbox=(10, 10, 10, 30)), replace(fish(), bbox=(0, 0, float("nan"), 30)),
    replace(fish(), class_name="noise"), replace(fish(), class_id=1),
])
def test_malformed_detections_do_not_create_identities(invalid):
    identities = ConfirmedFishIdentities()
    assert identities.update([invalid]) == []
    assert identities.update([invalid]) == []
    assert identities.diagnostics()["confirmed_fish_ids"] == 0


def test_confirmation_preserves_a_fast_two_frame_count_line_crossing():
    identities = ConfirmedFishIdentities()
    counter = TrackingManager(TrackingConfig(line_position=.5))
    first = identities.update([fish(x=25)], timestamp=0)
    assert counter.update(first, (100, 60), timestamp=0) == []
    second = identities.update([fish(x=55)], timestamp=.1)
    events = counter.update(second, (100, 60), timestamp=.1)
    assert [event.track_id for event in events] == [1]
    assert counter.counters()["total"] == 1


def test_explicit_session_reset_reuses_first_id_and_clears_counts(tmp_path):
    identities = ConfirmedFishIdentities()
    model = SimpleNamespace(reset_tracker=identities.reset)
    state = InspectionState()
    service = CameraInspectionService(state, model, camera_profile_path=tmp_path / "camera.yaml")
    identities.update([fish()])
    confirmed = service._scope_tracker_ids(identities.update([fish()]))
    assert confirmed[0].track_id == 1
    service.reset_session()
    identities.update([fish(2000)])
    assert service._scope_tracker_ids(identities.update([fish(2000)]))[0].track_id == 1
    assert state.snapshot()["counters"]["total"] == 0


def test_stop_or_calibration_tracker_reset_keeps_existing_history_ids_unique(tmp_path):
    identities = ConfirmedFishIdentities()
    service = CameraInspectionService(InspectionState(), SimpleNamespace(reset_tracker=identities.reset),
                                      camera_profile_path=tmp_path / "camera.yaml")
    identities.update([fish()])
    previous = service._scope_tracker_ids(identities.update([fish()]))[0].track_id
    service._reset_model_tracker()
    identities.update([fish(5000)])
    current = service._scope_tracker_ids(identities.update([fish(5000)]))[0].track_id
    assert previous == 1
    assert current == 2


def test_identity_reset_clears_pending_candidates_and_counter():
    identities = ConfirmedFishIdentities()
    identities.update([fish()])
    identities.update([fish()])
    identities.reset()
    assert identities.diagnostics()["confirmed_fish_ids"] == 0
    assert identities.update([fish(800)])[0].track_id is None
    assert identities.update([fish(800)])[0].track_id == 1


def test_continuous_weak_native_observations_keep_a_confirmed_id_alive():
    identities = ConfirmedFishIdentities()
    identities.update([fish()])
    identities.update([fish()])
    for _ in range(100):
        assert identities.update([], minimum_confidence=.5, observed_tracks=[fish(confidence=.2)]) == []
    assert identities.update([fish()], minimum_confidence=.5)[0].track_id == 1
    assert identities.diagnostics()["confirmed_fish_ids"] == 1


def test_native_tentative_evidence_preserves_the_true_first_position():
    identities = ConfirmedFishIdentities()
    first = identities.update([fish(None, x=25)], observed_tracks=[fish(500, x=25)],
                              minimum_confidence=.5, timestamp=0)
    assert first[0].track_id is None
    confirmed = identities.update([fish(500, x=55)], observed_tracks=[fish(500, x=55)],
                                  minimum_confidence=.5, timestamp=.1)[0]
    assert confirmed.track_id == 1
    assert confirmed.confirmation.bbox == fish(x=25).bbox
    counter = TrackingManager(TrackingConfig(line_position=.5))
    assert len(counter.update([confirmed], (100, 60), timestamp=.1)) == 1

from __future__ import annotations

from copy import deepcopy

import pytest

from src.evaluation import runtime_benchmark as benchmark


def running_status():
    return {'inspection_status': 'running', 'camera_status': 'connected', 'runtime_mode': 'whole_fish',
            'model_info': {'detector': {'status': 'ready'}, 'quality': {'status': 'ready'}}}


def test_stopped_camera_is_not_a_measurement(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    responses = {'/api/status': {'inspection_status': 'stopped', 'camera_status': 'disconnected'},
                 '/api/debug/runtime': {'enabled': False, 'paused': False}, '/api/camera/settings': {}}
    result = benchmark.collect('http://127.0.0.1:8000', 'empty', fetch=lambda _base, path: responses[path],
                               sleep=lambda _seconds: pytest.fail('should not wait for stopped camera'))
    assert result['status'] == 'NOT_MEASURED'
    assert 'not running' in result['reason']
    assert 'rates' not in result


def test_debug_capture_is_not_a_clean_baseline(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    responses = {'/api/status': {'inspection_status': 'running', 'camera_status': 'connected'},
                 '/api/debug/runtime': {'enabled': True}, '/api/camera/settings': {}}
    result = benchmark.collect('http://localhost:8000', 'one_fish', fetch=lambda _base, path: responses[path])
    assert result['status'] == 'NOT_MEASURED'
    assert 'Debug' in result['reason']


def test_rates_use_counter_deltas_and_preserve_rolling_timings(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    elapsed = [0.0]
    def sleep(value): elapsed[0] += value
    def fetch(_base, path):
        if path == '/api/status':
            return running_status()
        if path == '/api/camera/settings':
            return {}
        count = int(elapsed[0])
        return deepcopy({'enabled': False, 'paused': False,
                         'frame_queue': {'captured_frames': count * 10, 'processed_frames': count * 5, 'dropped_frames': count * 5},
                         'performance': {'counters': {'processed_frame': count * 4, 'model1': count * 5, 'model2': count},
                                         'timings': {'model1_inference': {'count': 100, 'p50': 100, 'p95': 200}}}})
    result = benchmark.collect('http://localhost:8000', 'overlap', duration=60, warmup=0, interval=10,
                               fetch=fetch, sleep=sleep, clock=lambda: elapsed[0])
    assert result['status'] == 'MEASURED'
    assert result['rates']['captured_frames_per_second'] == 10
    assert result['rates']['processed_frame_per_second'] == 4
    assert result['rates']['processed_frames_per_second'] == 5
    assert result['final_rolling_timings']['model1_inference']['p95'] == 200


def test_remote_url_or_invalid_duration_is_rejected():
    with pytest.raises(ValueError):
        benchmark.collect('http://example.com', 'empty')
    with pytest.raises(ValueError):
        benchmark.collect('http://localhost', 'empty', duration=2)
    with pytest.raises(ValueError):
        benchmark.collect('http://localhost', 'empty', interval=0.01)
    assert benchmark._counter_delta({'x': 1}, {'x': True}, 'x') is None
    assert benchmark._counter_delta({'x': 1}, {}, 'x') is None


def test_unavailable_model_and_preview_mode_are_not_measurements(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    for change, reason in [({'runtime_mode': 'part_preview'}, 'mode'),
                           ({'model_info': {'detector': {'status': 'ready'}, 'quality': {'status': 'unavailable'}}}, 'model')]:
        status = running_status() | change
        responses = {'/api/status': status, '/api/debug/runtime': {'enabled': False}, '/api/camera/settings': {}}
        result = benchmark.collect('http://localhost', 'empty', fetch=lambda _base, path: responses[path])
        assert result['status'] == 'NOT_MEASURED'
        assert reason in result['reason']


def test_zero_activity_is_not_a_measurement(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    elapsed = [0.0]
    def sleep(value): elapsed[0] += value
    responses = {'/api/status': running_status(), '/api/debug/runtime': {'enabled': False, 'frame_queue': {}, 'performance': {}}, '/api/camera/settings': {}}
    result = benchmark.collect('http://localhost', 'empty', warmup=0, interval=10,
                               fetch=lambda _base, path: responses[path], sleep=sleep, clock=lambda: elapsed[0])
    assert result['status'] == 'NOT_MEASURED'
    assert 'activity' in result['reason']


def test_changed_session_is_not_a_measurement(monkeypatch):
    monkeypatch.setattr(benchmark, '_hardware', lambda: {})
    elapsed = [0.0]
    def sleep(value): elapsed[0] += value
    def fetch(_base, path):
        if path == '/api/status':
            return running_status() | {'durable_session': {'session_id': 'a' if elapsed[0] < 60 else 'b'}}
        if path == '/api/camera/settings':
            return {}
        count = int(elapsed[0])
        return {'enabled': False, 'frame_queue': {'captured_frames': count},
                'performance': {'counters': {'processed_frame': count, 'model1': count}}}
    result = benchmark.collect('http://localhost', 'empty', warmup=0, interval=10,
                               fetch=fetch, sleep=sleep, clock=lambda: elapsed[0])
    assert result['status'] == 'NOT_MEASURED'
    assert 'durable_session' in result['reason']

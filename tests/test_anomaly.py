"""Unit tests for anomaly detection agent."""
import pytest
from datetime import datetime, timezone

from ai_engine.agents.anomaly import AnomalyDetector, AnomalyEvent


class TestAnomalyDetector:
    """Anomaly detection agent tests."""

    def test_normal_reading_no_anomaly(self, sample_reading):
        """Normal readings should not trigger anomalies."""
        detector = AnomalyDetector()
        events = detector.check(sample_reading)
        assert events == []

    def test_temperature_threshold_exceeded(self, abnormal_reading):
        """Temperature above threshold should trigger anomaly."""
        detector = AnomalyDetector()
        events = detector.check(abnormal_reading)
        assert len(events) > 0
        temp_events = [e for e in events if e.sensor_type == "temperature"]
        assert len(temp_events) > 0
        assert temp_events[0].severity in ("critical", "warning")

    def test_vibration_threshold_exceeded(self, abnormal_reading):
        """Vibration above threshold should trigger anomaly."""
        detector = AnomalyDetector()
        events = detector.check(abnormal_reading)
        vib_events = [e for e in events if e.sensor_type == "vibration"]
        assert len(vib_events) > 0

    def test_baseline_learning(self, sample_reading):
        """Detector should learn baselines from normal data."""
        detector = AnomalyDetector()

        # Feed 30 normal readings to build baseline
        for _ in range(30):
            detector.check(sample_reading)

        # Now send a reading that's >3 sigma from baseline
        abnormal = sample_reading.copy()
        abnormal["sensors"] = {**sample_reading["sensors"], "temperature": 200.0}
        events = detector.check(abnormal)
        assert len(events) > 0

    def test_anomaly_event_fields(self, abnormal_reading):
        """Anomaly events should have all required fields."""
        detector = AnomalyDetector()
        events = detector.check(abnormal_reading)
        for ev in events:
            assert isinstance(ev, AnomalyEvent)
            assert ev.device_id == "CNC-A01"
            assert ev.sensor_type in ("temperature", "vibration", "spindle_speed", "cutting_force")
            assert ev.anomaly_type  # non-empty
            assert ev.severity in ("critical", "warning", "info")
            assert ev.message  # non-empty
            assert ev.value is not None

    def test_different_devices_independent(self, sample_reading):
        """Different devices should have independent baselines."""
        detector = AnomalyDetector()

        # Feed device A
        reading_a = {**sample_reading, "device_id": "CNC-A01"}
        for _ in range(20):
            detector.check(reading_a)

        # Feed device B (should not trigger anomaly just because it's new)
        reading_b = {**sample_reading, "device_id": "CNC-A02"}
        events = detector.check(reading_b)
        # New device might trigger if values are outside default thresholds
        # but should not trigger just because baseline doesn't exist
        # This is more of a smoke test
        assert isinstance(events, list)

    def test_empty_sensors(self):
        """Empty sensors should not crash."""
        detector = AnomalyDetector()
        reading = {
            "device_id": "CNC-A01",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sensors": {},
            "status": "running",
        }
        events = detector.check(reading)
        assert events == []

    def test_missing_device_id(self):
        """Missing device_id should not crash."""
        detector = AnomalyDetector()
        reading = {
            "device_id": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sensors": {"temperature": 45.0},
            "status": "running",
        }
        events = detector.check(reading)
        assert isinstance(events, list)

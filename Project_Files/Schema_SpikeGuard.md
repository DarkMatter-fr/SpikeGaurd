# Data Schema - SpikeGuard v1.0

This document outlines the data structures utilized during the runtime of the SpikeGuard application. In compliance with security and privacy requirements, all biometric and video data is processed in-memory (RAM) and immediately discarded [cite: 2].

## 1. System Configuration Schema
Defines the initialization parameters for the application [cite: 3].

```json
{
  "camera_index": 0,
  "target_fps": 15,
  "sliding_window_seconds": 3,
  "snn_spike_threshold": 45,
  "alert_cooldown_seconds": 5
}
```

## 2. Frame Feature Extraction Payload
Represents the spatial metrics extracted from a single video frame [cite: 2, 3].

```json
{
  "timestamp_ms": 1672531200000,
  "face_detected": true,
  "bounding_box": {
    "x": 120,
    "y": 80,
    "width": 200,
    "height": 200
  },
  "metrics": {
    "left_ear": 0.28,
    "right_ear": 0.29,
    "avg_ear": 0.285,
    "hpe_pitch": -15.2,
    "hpe_yaw": 2.1,
    "hpe_roll": 0.5
  }
}
```

## 3. Neuromorphic Temporal Buffer
Represents the 3-second sliding window buffer used by the inference engine [cite: 2, 3].

```json
{
  "window_start_ms": 1672531197000,
  "window_end_ms": 1672531200000,
  "total_frames_processed": 45,
  "spike_train": [0, 1, 0, 0, 1, 1, 0, 1],
  "accumulated_spikes": 32,
  "state": "AWAKE"
}
```

## 4. Alert Event Log
Transient record of a triggered alert [cite: 2].

```json
{
  "event_id": "evt_987654321",
  "timestamp_ms": 1672531200000,
  "trigger_metrics": {
    "accumulated_spikes": 48,
    "threshold": 45
  },
  "action_taken": [
    "AUDIBLE_ALARM",
    "VISUAL_OVERLAY"
  ]
}
```

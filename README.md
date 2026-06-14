# SpikeGuard

SpikeGuard is a local, software-only drowsy-driver monitoring app. It uses a laptop or USB webcam, extracts face/eye/head-pose telemetry, feeds a neuromorphic Leaky Integrate-and-Fire spike engine, and triggers audio/visual alerts when drowsiness is detected.

## Features

- Browser-permission webcam capture or mock simulation mode
- Eye Aspect Ratio (EAR), Mouth Aspect Ratio (MAR), and head-pose telemetry
- C++ SNN inference engine loaded from Python with `ctypes`
- Browser dashboard served locally from the backend
- Sensitivity presets: Relaxed, Standard, Strict
- Custom EAR threshold, rolling-window duration, and spike threshold
- Local persisted settings in `spikeguard_config.json`
- Local CSV session logs in `logs/`
- Manual alert dismissal with the dashboard button or Space bar
- Mid-feed head-drop line: alarm after the face stays below the line for 10 seconds
- Eye-closure alarm after EAR remains below threshold for 5 seconds

## Project Structure

```text
.
├── build.bat                  # Builds snn_engine.dll from C++
├── requirements.txt           # Python dependencies
├── snn_engine.dll             # Built SNN engine used by Python
├── face_landmarker.task       # MediaPipe face landmark model
├── src/
│   ├── main.py                # Backend, HTTP server, WebSocket stream, logging
│   ├── inference/             # C++ SNN engine source
│   ├── pipeline/tracker.py    # Face tracking, EAR/MAR/HPE, SNN bridge
│   └── ui/                    # Static frontend dashboard
└── Project_Files/             # PRD and architecture notes
```

## Prerequisites

- Python 3.10+ recommended
- `g++` available on PATH if rebuilding the C++ DLL
- A webcam for real monitoring, or use `--mock` for simulation

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

Build the C++ SNN engine if `snn_engine.dll` is missing or source changed:

```powershell
.\build.bat
```

## Start the App

Run with browser webcam permission flow:

```powershell
python src\main.py
```

Open `http://localhost:8000`, then click **Start camera** and allow webcam access in the browser prompt.

The camera feed shows a dotted midline. If the detected head/face center remains below that line for 10 seconds, the alarm triggers. If the eyes remain closed for 5 seconds, the alarm also triggers. **Dismiss alert** silences the siren and hides the overlay until the driver returns to a normal state.

Run with the mock simulator:

```powershell
python src\main.py --mock
```

Run with Python/OpenCV camera capture instead of browser permission:

```powershell
python src\main.py --local-camera
```

Open the dashboard:

```text
http://localhost:8000
```

The backend also starts a WebSocket stream on:

```text
ws://localhost:8765
```

## Common Options

Use a different HTTP port:

```powershell
python src\main.py --mock --port 8080
```

Override target FPS:

```powershell
python src\main.py --mock --fps 30
```

Override the initial spike threshold:

```powershell
python src\main.py --mock --threshold 18
```

## Frontend vs Backend

There is no separate frontend build step. The frontend is plain HTML/CSS/JS in `src\ui`, and the Python backend serves it automatically.

- Backend entrypoint: `python src\main.py --mock` or `python src\main.py`
- Frontend URL: `http://localhost:8000`
- Runtime settings API: `GET/POST http://localhost:8000/api/config`
- Session summary API: `GET http://localhost:8000/api/summary`

## Runtime Files

The app creates local-only runtime files:

- `spikeguard_config.json` stores sensitivity and threshold settings.
- `logs/session_YYYYMMDD_HHMMSS.csv` records drowsiness event start/end rows.

These files are ignored by Git because they are local session state.

## Troubleshooting

If the app says the SNN DLL is missing, run:

```powershell
.\build.bat
```

If browser webcam access fails, make sure the page is opened from `http://localhost:8000` and allow camera permission when prompted. You can also run mock mode to verify the UI and inference pipeline:

```powershell
python src\main.py --mock
```

If MediaPipe cannot initialize, SpikeGuard falls back to OpenCV Haar cascade tracking. The MediaPipe model file `face_landmarker.task` is included in the project for the full landmark pipeline.

# Implementation Plan - SpikeGuard v1.0

SpikeGuard is an SNN-based real-time driver drowsiness detection system. This plan details a high-performance, responsive hybrid solution that uses a C++ core inference engine for spiking neural networks, a Python pipeline for video acquisition and landmark tracking, and a premium web-based local dashboard for monitoring, graphs, and audible/visual alarms.

---

## User Review Required

> [!IMPORTANT]
> **Hybrid C++/Python Architecture**: To satisfy the technical requirements (low CPU overhead and SNN simulation in C++) while avoiding complex C++ UI linking (Qt/CMake setup on Windows), we will build the core LIF SNN engine as a C++ DLL compiled using standard `g++` (available in the environment) and load it into Python via `ctypes`.
> 
> **Premium Local Web Dashboard**: Python will run a local WebSocket server to stream real-time telemetry (video frames, EAR/HPE metrics, SNN potentials, and alert states) to a modern, glassmorphic HTML/CSS/JS frontend dashboard. Visual overlays and high-decibel audible alerts (using the HTML5 Web Audio API) will be rendered directly in the browser.
> 
> **Mock Camera Mode**: To allow verification in environments without a webcam (or with permissions disabled), we will include a synthetic simulation mode. This mode generates realistic driver signals (blinking, head tilting) to fully test the SNN and alert systems.

---

## Open Questions

There are no major open questions, but please let us know if you prefer a different SNN model or threshold configuration than the standard Leaky Integrate-and-Fire (LIF) model defined below.

---

## Proposed Changes

### Build Scripts

#### [NEW] [build.bat](file:///c:/Coding/SpikeGaurd/build.bat)
Simple batch script to compile the C++ inference engine into a dynamic link library (`snn_engine.dll`) using `g++`.

---

### Core Inference Engine (C++)

#### [NEW] [snn_engine.h](file:///c:/Coding/SpikeGaurd/src/inference/snn_engine.h)
Defines the `SNNEngine` class implementing a Leaky Integrate-and-Fire (LIF) neuron model, sliding window buffers, and temporal spike tracking.

#### [NEW] [snn_engine.cpp](file:///c:/Coding/SpikeGaurd/src/inference/snn_engine.cpp)
Implements the LIF neuron membrane potential accumulation, decay, threshold checks, dynamic window updates, and exports a C-compatible API (`extern "C"`) for loading via Python.

---

### Preprocessing & Face Tracking (Python)

#### [NEW] [tracker.py](file:///c:/Coding/SpikeGaurd/src/pipeline/tracker.py)
Implements the OpenCV video acquisition and MediaPipe Face Mesh landmark tracking. Calculates the Eye Aspect Ratio (EAR) and Head Pose Estimation (HPE) (using 3D canonical landmarks and PnP solver) at 15+ FPS. Integrates with the C++ SNN engine via `ctypes`.

#### [NEW] [main.py](file:///c:/Coding/SpikeGaurd/src/main.py)
Entry point of the system. Manages configuration loading, starts the local HTTP and WebSocket server, and runs the video processing loop. Supports `--mock` flag for synthetic verification.

---

### Web Dashboard & UI (HTML5/CSS/JS)

#### [NEW] [index.html](file:///c:/Coding/SpikeGaurd/src/ui/index.html)
A beautiful, glassmorphic layout featuring the webcam container, real-time EAR and HPE monitors, an SNN spike raster chart, and an emergency visual overlay.

#### [NEW] [index.css](file:///c:/Coding/SpikeGaurd/src/ui/index.css)
Premium dark-theme styling, featuring smooth gradients, glowing highlights, glassmorphism backdrops, and alert state pulse animations.

#### [NEW] [dashboard.js](file:///c:/Coding/SpikeGaurd/src/ui/dashboard.js)
Establishes connection to the WebSocket server, draws real-time landmarks and stats, renders micro-animations, and generates high-decibel alarm tones using the Web Audio API when drowsiness is flagged.

---

## Verification Plan

### Automated Tests
We will run automated unit tests to verify the C++ SNN engine.
- Compile and run simple tests checking that membrane potential decays over time and spikes when the inputs exceed thresholds.

### Manual Verification
1. Run compilation of the C++ SNN DLL:
   ```cmd
   build.bat
   ```
2. Start the application in simulated (mock) mode:
   ```cmd
   python src/main.py --mock
   ```
3. Open the local dashboard in a web browser (`http://localhost:8000`).
4. Verify the dashboard receives telemetries, shows graphs, and triggers the audio-visual alert during simulated drowsiness events.
5. Verify on a real camera feed (if available) by running:
   ```cmd
   python src/main.py
   ```
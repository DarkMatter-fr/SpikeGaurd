# Technical Requirements Document - SpikeGuard

**Project:** SpikeGuard v1.0

## 1. Introduction
SpikeGuard is a software-based driver monitoring system designed to detect operator drowsiness in real-time. By utilizing the existing camera hardware on computational devices, the system monitors facial landmarks and eye aspect ratios to trigger preemptive alerts. The core processing engine leverages neuromorphic computing principles, specifically Spiking Neural Networks (SNNs), to achieve optimal inference with reduced power consumption.

## 2. System Architecture
The system is composed of three primary modules operating within a continuous feedback loop:

* **Video Acquisition Module:** Interfaces with the local webcam to capture real-time video frames.
* **Spatial Preprocessing Pipeline:** Standardizes input frames and extracts bounding boxes around the face and eyes.
* **Neuromorphic Inference Engine:** Converts spatial inputs into temporal spike trains to evaluate cognitive states (awake vs. drowsy).

> **Architecture Note:** As SNNs are deployed on standard von Neumann architectures, the inference engine utilizes a highly optimized C++ backend to simulate the temporal dynamics of the spikes efficiently, ensuring minimal CPU overhead.

## 3. Technology Stack

| Component | Technology / Language | Justification |
| :--- | :--- | :--- |
| **Core Logic & Processing** | C++17 / Python | C++ provides the necessary low-level memory management and execution speed for real-time video processing and efficient SNN simulation. |
| **Computer Vision** | OpenCV | Industry standard for high-performance facial landmark detection and frame manipulation. |
| **Neuromorphic Framework** | snnTorch or Norse (Python) -> ONNX | Facilitates the training of SNN models, which are then exported and consumed via a C++ inference runtime. |
| **User Interface** | Qt (Desktop) or WebRTC (Web App) | Cross-platform compatibility for local desktop deployment or browser-based execution. |

## 4. Functional Requirements
* **FR-01: Face and Eye Tracking:** The system must continuously track the driver's face and eyes under varying lighting conditions (daylight, cabin lighting).
* **FR-02: Drowsiness Metric Calculation:** The system must calculate the Eye Aspect Ratio (EAR) and Head Pose Estimation (HPE) at a minimum rate of 15 frames per second.
* **FR-03: SNN Thresholding:** The inference engine must process EAR and HPE historical data over a 3-second sliding window, converting the data into spike trains. If the spike count exceeds the predefined threshold parameter, a drowsiness event is flagged.
* **FR-04: Alert Generation:** Upon flagging a drowsiness event, the system must trigger an audible alarm and a visual indicator within 100 milliseconds.

## 5. Non-Functional Requirements
* **NFR-01: Latency:** Total pipeline latency from frame capture to alert generation must not exceed 200ms to ensure preemptive warning capability.
* **NFR-02: Computational Efficiency:** The application must utilize less than 15% of the processing capacity of a standard mid-tier CPU (e.g., Intel i5 / AMD Ryzen 5) to preserve battery life on unplugged devices.
* **NFR-03: Security & Privacy:** No video frames or biometric data may be transmitted over a network or stored on the local disk. All processing must occur in-memory (RAM) and be immediately discarded.

## 6. Deployment and Execution
The application is packaged as a standalone executable. For desktop execution, the system establishes a local event loop that binds to the default system camera (Index 0). The software requires explicit user consent to access the video feed upon initialization.

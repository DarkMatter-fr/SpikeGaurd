# Application Flow - SpikeGuard v1.0

This document outlines the sequential execution flow of the SpikeGuard drowsiness detection application, from initialization through the continuous monitoring loop to termination.

## 1. Initialization Phase
1. **Application Launch:** The user opens the SpikeGuard desktop or web application.
2. **Permission Request:** The system requests explicit permission to access the local camera hardware (defaulting to Camera Index 0).
   * *Condition (Denied):* Display permission error and halt.
   * *Condition (Approved):* Proceed to resource allocation.
3. **Resource Loading:**
   * Load facial detection models (e.g., OpenCV Haar cascades or optimized MTCNN).
   * Load pre-trained Spiking Neural Network (SNN) weights and configurations into the C++ inference engine.
   * Initialize the 3-second temporal sliding window memory buffer.

## 2. Continuous Processing Loop (15+ FPS)
Once initialized, the system enters an asynchronous loop to capture and evaluate data in real-time.

### A. Frame Acquisition & Preprocessing
1. Read the current video frame from the active camera stream.
2. Convert the frame to grayscale to reduce memory bandwidth and computational overhead.
3. Apply lightweight histogram equalization to normalize varying cabin lighting conditions.

### B. Feature Extraction
1. **Face Detection:** Isolate the driver's face within the frame.
2. **Landmark Extraction:** Identify specific geometric points representing the eyes, nose, and jawline.
3. **Metric Calculation:**
   * Calculate the **Eye Aspect Ratio (EAR)** to measure eyelid closure duration and blink frequency.
   * Calculate **Head Pose Estimation (HPE)** using facial landmarks to detect head dropping, tilting, or nodding.

### C. Neuromorphic Inference
1. Feed the calculated EAR and HPE metrics into the SNN engine.
2. Translate these spatial metrics into temporal spike trains based on the changing input values over time.
3. Accumulate the resulting spike signals within the active 3-second sliding window buffer.

## 3. Decision & Alerting Phase
1. **Threshold Evaluation:** Compare the total accumulated spike count in the current window against the defined empirical drowsiness threshold.
2. **State Determination:**
   * **State: Awake (Spikes < Threshold):** The driver is alert. The system drops the oldest frame data from the sliding window buffer and loops back to Step 2A.
   * **State: Drowsy (Spikes >= Threshold):** Neuromorphic patterns indicate critical fatigue. Proceed to Alert Trigger.
3. **Alert Trigger:**
   * Emit a high-decibel, high-priority audible alarm via the device speakers.
   * Flash a high-contrast visual warning overlay on the screen.
4. **Cooldown Reset:** Following an alert, enforce a 5-second suppression cooldown to prevent alarm overlap or spamming, then resume monitoring.

## 4. Termination Phase
1. The user manually halts the monitoring session or closes the application window.
2. The system forcefully releases the camera hardware lock.
3. All temporal buffers, extracted frames, and biometric telemetry are purged from RAM immediately to ensure absolute privacy (NFR-03 compliance).
4. The application process is terminated.

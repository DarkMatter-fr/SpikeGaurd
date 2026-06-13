#include "snn_engine.h"
#include <cmath>
#include <cstring>
#include <algorithm>

SNNEngine::SNNEngine(int target_fps, float sliding_window_seconds, float snn_spike_threshold)
    : fps(target_fps),
      spike_threshold(snn_spike_threshold),
      v_membrane(0.0f),
      v_threshold(1.0f),
      decay_rate(0.85f), // beta leak factor (0.85 means slow decay, integrating signals well)
      v_reset(0.0f) {
    
    window_size = static_cast<size_t>(target_fps * sliding_window_seconds);
    if (window_size == 0) window_size = 45; // Default fallback for 3s @ 15fps
    reset();
}

void SNNEngine::reset() {
    v_membrane = 0.0f;
    spike_train.clear();
    spike_train.assign(window_size, 0);
}

int SNNEngine::process_frame(
    float avg_ear, 
    float pitch, 
    float yaw, 
    float roll, 
    int& out_spike, 
    int& out_accumulated_spikes, 
    std::string& out_state,
    float& out_v_membrane
) {
    // 1. Calculate input current I from Eye Aspect Ratio (EAR)
    // Healthy open EAR is ~0.26 - 0.35. Closed EAR is < 0.20.
    float ear_current = 0.0f;
    float ear_threshold = 0.21f; // Threshold below which eyes are considered closing/closed
    if (avg_ear < ear_threshold) {
        // Linear scaling: lower EAR -> higher input current
        // E.g., if EAR is 0.10, diff is 0.11. Current = 0.11 * 18.0 = 1.98 (> threshold 1.0)
        ear_current = (ear_threshold - avg_ear) * 18.0f;
    }

    // 2. Calculate input current I from Head Pose Estimation (HPE)
    // Standard angles are in degrees.
    // Pitch: positive is head up, negative is head down (nodding).
    // Yaw: head turning left/right.
    // Roll: head tilting left/right.
    float hpe_current = 0.0f;
    
    // Head nodding down (pitch below -15 degrees)
    if (pitch < -12.0f) {
        hpe_current += std::abs(pitch + 12.0f) * 0.08f;
    }
    // Head nodding up excessively (pitch above 20 degrees, sleep posture)
    if (pitch > 20.0f) {
        hpe_current += (pitch - 20.0f) * 0.05f;
    }
    // Head turned away (yaw deviation > 20 degrees)
    float abs_yaw = std::abs(yaw);
    if (abs_yaw > 20.0f) {
        hpe_current += (abs_yaw - 20.0f) * 0.04f;
    }
    // Head tilting (roll deviation > 18 degrees)
    float abs_roll = std::abs(roll);
    if (abs_roll > 18.0f) {
        hpe_current += (abs_roll - 18.0f) * 0.04f;
    }

    // Total injected current
    float I = ear_current + hpe_current;

    // 3. Update LIF membrane potential (V = V * beta + I)
    v_membrane = (v_membrane * decay_rate) + I;

    // Guard against negative potentials
    if (v_membrane < 0.0f) {
        v_membrane = 0.0f;
    }

    // 4. Threshold checking & firing
    int spike = 0;
    if (v_membrane >= v_threshold) {
        spike = 1;
        v_membrane = v_reset; // Reset potential
    }

    // 5. Update temporal sliding window
    spike_train.push_back(spike);
    if (spike_train.size() > window_size) {
        spike_train.pop_front();
    }

    // 6. Accumulate spikes in window
    int total_spikes = 0;
    for (int s : spike_train) {
        total_spikes += s;
    }

    // Save outputs
    out_spike = spike;
    out_accumulated_spikes = total_spikes;
    out_v_membrane = v_membrane;

    // Determine state
    if (total_spikes >= spike_threshold) {
        out_state = "DROWSY";
    } else {
        out_state = "AWAKE";
    }

    return 0;
}

// C Wrapper Implementations
extern "C" {
    void* create_snn_engine(int target_fps, float sliding_window_seconds, float snn_spike_threshold) {
        return new SNNEngine(target_fps, sliding_window_seconds, snn_spike_threshold);
    }

    void destroy_snn_engine(void* engine) {
        if (engine) {
            delete static_cast<SNNEngine*>(engine);
        }
    }

    int process_frame_dll(
        void* engine, 
        float avg_ear, 
        float pitch, 
        float yaw, 
        float roll, 
        int* out_spike, 
        int* out_accumulated_spikes, 
        char* out_state_str,
        float* out_v_membrane
    ) {
        if (!engine) return -1;
        std::string state;
        int result = static_cast<SNNEngine*>(engine)->process_frame(
            avg_ear, pitch, yaw, roll, 
            *out_spike, *out_accumulated_spikes, state, *out_v_membrane
        );
        std::strcpy(out_state_str, state.c_str());
        return result;
    }

    void reset_snn_engine(void* engine) {
        if (engine) {
            static_cast<SNNEngine*>(engine)->reset();
        }
    }
}

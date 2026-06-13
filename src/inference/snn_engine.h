#ifndef SNN_ENGINE_H
#define SNN_ENGINE_H

#include <vector>
#include <deque>
#include <string>

class SNNEngine {
public:
    SNNEngine(int target_fps, float sliding_window_seconds, float snn_spike_threshold);
    ~SNNEngine() = default;

    int process_frame(
        float avg_ear, 
        float pitch, 
        float yaw, 
        float roll, 
        int& out_spike, 
        int& out_accumulated_spikes, 
        std::string& out_state,
        float& out_v_membrane
    );

    // Reset potential and sliding window
    void reset();

private:
    int fps;
    size_t window_size;
    float spike_threshold;

    // LIF Neuron parameters
    float v_membrane;
    float v_threshold;
    float decay_rate; // beta (leak rate)
    float v_reset;

    std::deque<int> spike_train;
};

// C interface for ctypes dynamic loading
extern "C" {
    __declspec(dllexport) void* create_snn_engine(int target_fps, float sliding_window_seconds, float snn_spike_threshold);
    __declspec(dllexport) void destroy_snn_engine(void* engine);
    __declspec(dllexport) int process_frame_dll(
        void* engine, 
        float avg_ear, 
        float pitch, 
        float yaw, 
        float roll, 
        int* out_spike, 
        int* out_accumulated_spikes, 
        char* out_state_str,
        float* out_v_membrane
    );
    __declspec(dllexport) void reset_snn_engine(void* engine);
}

#endif // SNN_ENGINE_H

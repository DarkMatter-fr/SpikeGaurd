import ctypes
import os
import sys

def main():
    dll_path = os.path.abspath("snn_engine.dll")
    if not os.path.exists(dll_path):
        print(f"Error: DLL not found at {dll_path}")
        sys.exit(1)

    print(f"Loading SNN Engine DLL from {dll_path}...")
    try:
        dll = ctypes.CDLL(dll_path)
    except Exception as e:
        print(f"Failed to load DLL: {e}")
        sys.exit(1)

    # Declare types
    dll.create_snn_engine.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float]
    dll.create_snn_engine.restype = ctypes.c_void_p

    dll.destroy_snn_engine.argtypes = [ctypes.c_void_p]
    dll.destroy_snn_engine.restype = None

    dll.process_frame_dll.argtypes = [
        ctypes.c_void_p,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_float)
    ]
    dll.process_frame_dll.restype = ctypes.c_int

    # Parameters: 15 FPS, 3 seconds window (45 frames), threshold 20 spikes
    fps = 15
    window_sec = 3.0
    threshold = 20.0
    
    engine = dll.create_snn_engine(fps, window_sec, threshold)
    print("SNN Engine created successfully!")

    # Helper function to run one frame
    def run_frame(ear, pitch, yaw, roll):
        spike = ctypes.c_int(0)
        accum = ctypes.c_int(0)
        state_buf = ctypes.create_string_buffer(32)
        v_memb = ctypes.c_float(0.0)
        
        res = dll.process_frame_dll(
            engine,
            ctypes.c_float(ear),
            ctypes.c_float(pitch),
            ctypes.c_float(yaw),
            ctypes.c_float(roll),
            ctypes.byref(spike),
            ctypes.byref(accum),
            state_buf,
            ctypes.byref(v_memb)
        )
        if res != 0:
            print("Error running process_frame_dll")
            return None
        
        return {
            "spike": spike.value,
            "accumulated_spikes": accum.value,
            "state": state_buf.value.decode('utf-8'),
            "v_membrane": v_memb.value
        }

    # Test Case 1: Normal alert state (Normal EAR ~0.3, no head nod/turn)
    print("\n--- Test Case 1: Normal Alert State (30 frames) ---")
    all_awake = True
    for i in range(30):
        out = run_frame(0.30, 0.0, 0.0, 0.0)
        if out["spike"] != 0 or out["state"] != "AWAKE":
            all_awake = False
        if i % 10 == 0:
            print(f"Frame {i:02d}: EAR={0.30:.2f}, V_memb={out['v_membrane']:.4f}, Spike={out['spike']}, Accum={out['accumulated_spikes']}, State={out['state']}")
    print("Result Case 1:", "PASS" if all_awake else "FAIL")

    # Test Case 2: Eye closure (Drowsiness)
    print("\n--- Test Case 2: Drowsiness Eye Closure (Closed EAR ~0.12, 35 frames) ---")
    drowsy_triggered = False
    for i in range(35):
        out = run_frame(0.12, 0.0, 0.0, 0.0)
        if out["state"] == "DROWSY":
            drowsy_triggered = True
        if i % 5 == 0 or out["state"] == "DROWSY":
            print(f"Frame {i:02d}: EAR={0.12:.2f}, V_memb={out['v_membrane']:.4f}, Spike={out['spike']}, Accum={out['accumulated_spikes']}, State={out['state']}")
            if out["state"] == "DROWSY":
                print(f"--> Triggered DROWSY at frame {i}!")
                break
    print("Result Case 2:", "PASS" if drowsy_triggered else "FAIL")

    # Clean up
    dll.destroy_snn_engine(engine)
    print("\nSNN Engine destroyed. Validation complete.")

if __name__ == "__main__":
    main()

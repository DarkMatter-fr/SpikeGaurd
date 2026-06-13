import os
import sys
import argparse
import asyncio
import json
import base64
import math
import cv2
import numpy as np
import http.server
import socketserver
import threading
import ctypes

from pipeline.tracker import DriverTracker

# Global set of connected WebSocket clients
connected_clients = set()
global_tracker = None

def run_http_server(port=8000):
    ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui"))
    
    class SafeHTTPHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ui_dir, **kwargs)
            
        def log_message(self, format, *args):
            # Suppress HTTP request logs to keep terminal output clean
            pass

    # Allow immediate reuse of socket address
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), SafeHTTPHandler) as httpd:
            print(f"[HTTP] Dashboard served at http://localhost:{port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"[HTTP] Failed to start HTTP server on port {port}: {e}")

async def ws_handler(websocket):
    global global_tracker
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("command") == "reset":
                print("[PROCESS] Received SNN reset command from UI.")
                if global_tracker:
                    global_tracker.reset_snn()
    except Exception as e:
        print(f"[WS] Exception in message loop: {e}")
    finally:
        connected_clients.remove(websocket)

async def broadcast_telemetry(payload):
    if not connected_clients:
        return
    message = json.dumps(payload)
    # Broadcast to all connected WebSockets
    await asyncio.gather(*[client.send(message) for client in connected_clients], return_exceptions=True)

async def video_loop(tracker, mock_mode, target_fps):
    cap = None
    if not mock_mode:
        print("[CAMERA] Initializing webcam...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[CAMERA] WARNING: Default webcam not found! Falling back to MOCK mode.")
            mock_mode = True
        else:
            print("[CAMERA] Webcam initialized successfully.")

    delay = 1.0 / target_fps
    sim_time = 0.0

    print(f"[PROCESS] Starting execution loop at {target_fps} FPS (Mock={mock_mode}).")

    try:
        while True:
            start_time = asyncio.get_event_loop().time()
            
            frame = None
            ear = 0.30
            pitch, yaw, roll = 0.0, 0.0, 0.0
            
            if mock_mode:
                # Create a synthetic image canvas (640x480)
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                # Draw dark space grid background
                frame[:, :] = [30, 20, 15] # HSL-like dark slate
                
                cycle_time = sim_time % 60.0
                state_lbl = "AWAKE"

                # Define mock variables according to 60-second cycle
                if 0.0 <= cycle_time < 15.0:
                    # Awake - normal blinking
                    if int(cycle_time) % 4 == 0 and (cycle_time - int(cycle_time)) < 0.25:
                        ear = 0.08  # Blink
                    else:
                        ear = 0.28 + 0.02 * math.sin(cycle_time * 2.0)
                    state_lbl = "ALERT (AWAKE)"
                elif 15.0 <= cycle_time < 30.0:
                    # Closed eyes (drowsiness phase 1)
                    ear = 0.08 + 0.01 * math.sin(cycle_time)
                    state_lbl = "EYES CLOSED (DROWSY)"
                elif 30.0 <= cycle_time < 45.0:
                    # Recovered awake state
                    if int(cycle_time) % 4 == 0 and (cycle_time - int(cycle_time)) < 0.25:
                        ear = 0.08
                    else:
                        ear = 0.27 + 0.01 * math.cos(cycle_time)
                    state_lbl = "RECOVERED (AWAKE)"
                else:
                    # Head nodding down (drowsiness phase 2)
                    nod_progress = (cycle_time - 45.0) / 15.0  # 0 to 1
                    pitch = -25.0 * math.sin(nod_progress * math.pi)
                    ear = 0.22 - 0.05 * math.sin(nod_progress * math.pi)
                    state_lbl = "HEAD NODDING (DROWSY)"

                # Draw synthetic face simulation on frame
                offset_y = int(pitch * 2.5)
                # Outer face circle
                cv2.circle(frame, (320, 240 + offset_y), 120, (50, 40, 35), -1)
                cv2.circle(frame, (320, 240 + offset_y), 120, (140, 110, 95), 2)
                
                # Left & Right eyes
                eye_h = 10 if ear > 0.15 else 2
                cv2.ellipse(frame, (270, 210 + offset_y), (15, eye_h), 0, 0, 360, (220, 220, 220), -1)
                cv2.ellipse(frame, (370, 210 + offset_y), (15, eye_h), 0, 0, 360, (220, 220, 220), -1)
                
                # Pupils (if eyes open)
                if ear > 0.15:
                    cv2.circle(frame, (270, 210 + offset_y), 5, (20, 30, 20), -1)
                    cv2.circle(frame, (370, 210 + offset_y), 5, (20, 30, 20), -1)
                
                # Nose
                cv2.polygon = np.array([
                    [320, 230 + offset_y],
                    [310, 260 + offset_y],
                    [330, 260 + offset_y]
                ], dtype=np.int32)
                cv2.fillPoly(frame, [cv2.polygon], (100, 75, 60))

                # Mouth
                mouth_h = 12 if pitch > -10 else 25
                cv2.ellipse(frame, (320, 310 + offset_y), (35, mouth_h), 0, 0, 360, (30, 15, 10), -1)

                # Overlay status text
                cv2.putText(frame, f"SIMULATOR MODE: {state_lbl}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
                cv2.putText(frame, f"Cycle Time: {cycle_time:.1f}s", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
                
            else:
                ret, img = cap.read()
                if not ret:
                    print("[CAMERA] Error reading frame from webcam.")
                    await asyncio.sleep(0.1)
                    continue
                # Horizontal mirror flip
                frame = cv2.flip(img, 1)

            # Process frame using DriverTracker
            if mock_mode:
                # Directly calculate SNN response using process_snn helper
                snn_out = tracker.process_snn(ear, pitch, yaw, roll)

                # Simulated sparse landmarks
                offset_y = int(pitch * 2.5)
                landmarks = [
                    {"x": 320, "y": 245 + offset_y}, # Nose
                    {"x": 270, "y": 210 + offset_y}, # Left Eye
                    {"x": 370, "y": 210 + offset_y}, # Right Eye
                    {"x": 320, "y": 310 + offset_y}  # Mouth
                ]

                payload = {
                    "width": 640,
                    "height": 480,
                    "face_detected": True,
                    "bounding_box": {"x": 200, "y": 120, "width": 240, "height": 240},
                    "metrics": {
                        "left_ear": round(ear, 3),
                        "right_ear": round(ear, 3),
                        "avg_ear": round(ear, 3),
                        "hpe_pitch": round(pitch, 1),
                        "hpe_yaw": round(yaw, 1),
                        "hpe_roll": round(roll, 1)
                    },
                    "snn": snn_out,
                    "landmarks": landmarks
                }
            else:
                payload = tracker.process_image(frame)

            # Encode frame to Base64 JPEG
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            jpg_b64 = base64.b64encode(buffer).decode('utf-8')
            payload["frame"] = f"data:image/jpeg;base64,{jpg_b64}"

            # Broadcast to clients
            await broadcast_telemetry(payload)

            # Control frequency
            sim_time += delay
            elapsed = asyncio.get_event_loop().time() - start_time
            sleep_time = max(0.001, delay - elapsed)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        print("[PROCESS] Loop cancelled.")
    finally:
        if cap is not None:
            cap.release()
            print("[CAMERA] Webcam hardware lock released.")

async def main():
    parser = argparse.ArgumentParser(description="SpikeGuard Drowsiness Detection System")
    parser.add_argument("--mock", action="store_true", help="Run in mock simulation mode")
    parser.add_argument("--port", type=int, default=8000, help="HTTP web server port")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket server port")
    parser.add_argument("--fps", type=int, default=15, help="Target processing FPS")
    parser.add_argument("--threshold", type=float, default=25.0, help="SNN accumulated spike threshold")
    
    args = parser.parse_args()

    # Load SNN tracker
    global global_tracker
    try:
        tracker = DriverTracker(target_fps=args.fps, sliding_window_sec=3.0, threshold_spikes=args.threshold)
        global_tracker = tracker
        print("[SYSTEM] SNN Tracker initialized successfully.")
    except Exception as e:
        print(f"[SYSTEM] FATAL: Initialization failed: {e}")
        sys.exit(1)

    # Start HTTP dashboard server in daemon thread
    http_thread = threading.Thread(target=run_http_server, args=(args.port,), daemon=True)
    http_thread.start()

    # Start WebSocket server
    import websockets
    print(f"[WS] WebSocket server starting on ws://localhost:{args.ws_port}")
    
    # Run server and loop
    async with websockets.serve(ws_handler, "localhost", args.ws_port):
        await video_loop(tracker, args.mock, args.fps)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] SpikeGuard stopped by user.")

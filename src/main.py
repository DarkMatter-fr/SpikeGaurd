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
import csv
from datetime import datetime, timezone

from pipeline.tracker import DriverTracker

# Global set of connected WebSocket clients
connected_clients = set()
global_tracker = None
session_logger = None
app_config = None
latest_browser_frame_at = None

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT_DIR, "spikeguard_config.json")
LOG_DIR = os.path.join(ROOT_DIR, "logs")

PRESETS = {
    "relaxed": {"threshold_spikes": 32.0, "ear_threshold": 0.19, "mar_threshold": 0.68, "window_seconds": 3.5},
    "standard": {"threshold_spikes": 25.0, "ear_threshold": 0.21, "mar_threshold": 0.60, "window_seconds": 3.0},
    "strict": {"threshold_spikes": 18.0, "ear_threshold": 0.23, "mar_threshold": 0.52, "window_seconds": 2.5},
}

DEFAULT_CONFIG = {
    "preset": "standard",
    "target_fps": 15,
    "threshold_spikes": 25.0,
    "ear_threshold": 0.21,
    "mar_threshold": 0.60,
    "window_seconds": 3.0,
    "alert_auto_dismiss_seconds": 5.0,
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except Exception as e:
            print(f"[CONFIG] Failed to read config, using defaults: {e}")
    return normalize_config(config)


def normalize_config(config):
    preset = str(config.get("preset", "standard")).lower()
    if preset in PRESETS:
        merged = DEFAULT_CONFIG.copy()
        merged.update(PRESETS[preset])
        merged.update(config)
        merged["preset"] = preset
    else:
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        merged["preset"] = "custom"

    merged["target_fps"] = max(5, min(30, int(merged.get("target_fps", 15))))
    merged["threshold_spikes"] = max(1.0, float(merged.get("threshold_spikes", 25.0)))
    merged["ear_threshold"] = max(0.10, min(0.35, float(merged.get("ear_threshold", 0.21))))
    merged["mar_threshold"] = max(0.30, min(1.20, float(merged.get("mar_threshold", 0.60))))
    merged["window_seconds"] = max(1.0, min(10.0, float(merged.get("window_seconds", 3.0))))
    return merged


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


class SessionLogger:
    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(LOG_DIR, f"session_{stamp}.csv")
        self.event_open = False
        self.event_start = None
        self.events = []
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["event", "timestamp_utc", "duration_seconds", "avg_ear", "mar", "pitch", "yaw", "roll", "source"])

    def update(self, payload, source="runtime"):
        state = payload.get("snn", {}).get("state")
        metrics = payload.get("metrics", {})
        if state == "DROWSY" and not self.event_open:
            self.event_open = True
            self.event_start = datetime.now(timezone.utc)
            self._write("start", self.event_start, "", metrics, source)
        elif state != "DROWSY" and self.event_open:
            self.close(metrics, source)

    def close(self, metrics=None, source="runtime"):
        if not self.event_open:
            return
        end = datetime.now(timezone.utc)
        duration = (end - self.event_start).total_seconds() if self.event_start else 0.0
        self.events.append(duration)
        self._write("end", end, f"{duration:.2f}", metrics or {}, source)
        self.event_open = False
        self.event_start = None

    def _write(self, event, timestamp, duration, metrics, source):
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                event,
                timestamp.isoformat(timespec="seconds"),
                duration,
                metrics.get("avg_ear", ""),
                metrics.get("mar", ""),
                metrics.get("hpe_pitch", ""),
                metrics.get("hpe_yaw", ""),
                metrics.get("hpe_roll", ""),
                source,
            ])

    def summary(self):
        active_duration = 0.0
        if self.event_open and self.event_start:
            active_duration = (datetime.now(timezone.utc) - self.event_start).total_seconds()
        durations = self.events + ([active_duration] if active_duration else [])
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "event_count": len(durations),
            "average_alert_duration": round(avg_duration, 2),
            "active_event": self.event_open,
            "log_path": self.path,
        }

def run_http_server(port=8000):
    ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui"))
    
    class SafeHTTPHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=ui_dir, **kwargs)
            
        def log_message(self, format, *args):
            # Suppress HTTP request logs to keep terminal output clean
            pass

        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/config":
                self._send_json(app_config)
                return
            if self.path == "/api/summary":
                self._send_json(session_logger.summary() if session_logger else {})
                return
            super().do_GET()

        def do_POST(self):
            global app_config, global_tracker
            if self.path != "/api/config":
                self._send_json({"error": "not_found"}, 404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                incoming = json.loads(body)
                if incoming.get("preset") in PRESETS:
                    next_config = DEFAULT_CONFIG.copy()
                    next_config.update(PRESETS[incoming["preset"]])
                    next_config.update(incoming)
                else:
                    next_config = app_config.copy()
                    next_config.update(incoming)
                    next_config["preset"] = "custom"
                app_config = normalize_config(next_config)
                save_config(app_config)
                if global_tracker:
                    global_tracker.update_runtime_config(
                        target_fps=app_config["target_fps"],
                        sliding_window_sec=app_config["window_seconds"],
                        threshold_spikes=app_config["threshold_spikes"],
                        config=app_config,
                    )
                self._send_json(app_config)
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

    # Allow immediate reuse of socket address
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), SafeHTTPHandler) as httpd:
            print(f"[HTTP] Dashboard served at http://localhost:{port}")
            httpd.serve_forever()
    except Exception as e:
        print(f"[HTTP] Failed to start HTTP server on port {port}: {e}")

async def ws_handler(websocket):
    global global_tracker, latest_browser_frame_at
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("command") == "reset":
                print("[PROCESS] Received SNN reset command from UI.")
                if global_tracker:
                    global_tracker.reset_snn()
                if session_logger:
                    session_logger.close(source="manual_dismiss")
            elif data.get("command") == "dismiss":
                print("[PROCESS] Received alert dismiss command from UI.")
                if session_logger:
                    session_logger.close(source="manual_dismiss")
            elif data.get("type") == "camera_frame" and global_tracker:
                frame_data = data.get("frame", "")
                if "," in frame_data:
                    frame_data = frame_data.split(",", 1)[1]
                try:
                    raw = base64.b64decode(frame_data)
                    img_array = np.frombuffer(raw, dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                    latest_browser_frame_at = datetime.now(timezone.utc)
                    payload = global_tracker.process_image(frame)
                    payload["source"] = "browser_camera"
                    payload["config"] = app_config
                    await broadcast_telemetry(payload)
                    if session_logger:
                        session_logger.update(payload, source="browser_camera")
                except Exception as e:
                    print(f"[WS] Failed to process browser camera frame: {e}")
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

async def video_loop(tracker, mock_mode, target_fps, local_camera=False):
    cap = None
    if not mock_mode and local_camera:
        print("[CAMERA] Initializing webcam...")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[CAMERA] WARNING: Default webcam not found! Falling back to MOCK mode.")
            mock_mode = True
        else:
            print("[CAMERA] Webcam initialized successfully.")
    elif not mock_mode:
        print("[CAMERA] Waiting for browser camera frames from dashboard permission flow.")

    delay = 1.0 / target_fps
    sim_time = 0.0

    print(f"[PROCESS] Starting execution loop at {target_fps} FPS (Mock={mock_mode}).")

    try:
        while True:
            start_time = asyncio.get_event_loop().time()
            
            frame = None
            ear = 0.30
            mar = 0.20
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
                    head_drop_seconds = 0.0
                    eye_closed_seconds = 0.0
                elif 15.0 <= cycle_time < 30.0:
                    # Closed eyes (drowsiness phase 1)
                    ear = 0.08 + 0.01 * math.sin(cycle_time)
                    state_lbl = "EYES CLOSED (DROWSY)"
                    head_drop_seconds = 0.0
                    eye_closed_seconds = cycle_time - 15.0
                elif 30.0 <= cycle_time < 45.0:
                    # Recovered awake state
                    if int(cycle_time) % 4 == 0 and (cycle_time - int(cycle_time)) < 0.25:
                        ear = 0.08
                    else:
                        ear = 0.27 + 0.01 * math.cos(cycle_time)
                    state_lbl = "RECOVERED (AWAKE)"
                    head_drop_seconds = 0.0
                    eye_closed_seconds = 0.0
                else:
                    # Head nodding down (drowsiness phase 2)
                    nod_progress = (cycle_time - 45.0) / 15.0  # 0 to 1
                    pitch = -25.0 * math.sin(nod_progress * math.pi)
                    ear = 0.22 - 0.05 * math.sin(nod_progress * math.pi)
                    state_lbl = "HEAD NODDING (DROWSY)"
                    mar = 0.72 if 50.0 <= cycle_time < 55.0 else 0.30
                    head_drop_seconds = cycle_time - 45.0
                    eye_closed_seconds = 0.0

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
                mouth_h = 26 if mar > 0.60 else (12 if pitch > -10 else 25)
                cv2.ellipse(frame, (320, 310 + offset_y), (35, mouth_h), 0, 0, 360, (30, 15, 10), -1)

                # Overlay status text
                cv2.putText(frame, f"SIMULATOR MODE: {state_lbl}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
                cv2.putText(frame, f"Cycle Time: {cycle_time:.1f}s", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
                
            elif local_camera:
                ret, img = cap.read()
                if not ret:
                    print("[CAMERA] Error reading frame from webcam.")
                    await asyncio.sleep(0.1)
                    continue
                # Horizontal mirror flip
                frame = cv2.flip(img, 1)
            else:
                await asyncio.sleep(0.25)
                continue

            # Process frame using DriverTracker
            if mock_mode:
                # Directly calculate SNN response using process_snn helper
                snn_out = tracker.process_snn(ear, pitch, yaw, roll, mar)

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
                        "mar": round(mar, 3),
                        "hpe_pitch": round(pitch, 1),
                        "hpe_yaw": round(yaw, 1),
                        "hpe_roll": round(roll, 1),
                        "head_drop_seconds": round(head_drop_seconds, 1),
                        "eye_closed_seconds": round(eye_closed_seconds, 1),
                        "head_line_y": 240.0
                    },
                    "snn": snn_out,
                    "landmarks": landmarks
                }
                payload["snn"]["head_drop_threshold_seconds"] = 10.0
                payload["snn"]["eye_closed_threshold_seconds"] = 5.0
                if head_drop_seconds >= 10.0:
                    payload["snn"]["state"] = "DROWSY"
                    payload["snn"]["head_drop_alarm"] = True
                    payload["snn"]["reason"] = "HEAD_DROP_10S"
                if eye_closed_seconds >= 5.0:
                    payload["snn"]["state"] = "DROWSY"
                    payload["snn"]["eye_closed_alarm"] = True
                    payload["snn"]["reason"] = "EYES_CLOSED_5S"
            else:
                payload = tracker.process_image(frame)

            # Encode frame to Base64 JPEG
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            jpg_b64 = base64.b64encode(buffer).decode('utf-8')
            payload["frame"] = f"data:image/jpeg;base64,{jpg_b64}"
            payload["config"] = app_config

            # Broadcast to clients
            await broadcast_telemetry(payload)
            if session_logger:
                session_logger.update(payload, source="mock" if mock_mode else "camera")

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
    parser.add_argument("--fps", type=int, default=None, help="Target processing FPS")
    parser.add_argument("--threshold", type=float, default=None, help="SNN accumulated spike threshold")
    parser.add_argument("--local-camera", action="store_true", help="Capture webcam from Python instead of browser permission flow")
    
    args = parser.parse_args()
    global app_config, session_logger
    app_config = load_config()
    if args.fps:
        app_config["target_fps"] = args.fps
    if args.threshold:
        app_config["threshold_spikes"] = args.threshold
    app_config = normalize_config(app_config)
    save_config(app_config)
    session_logger = SessionLogger()

    # Load SNN tracker
    global global_tracker
    try:
        tracker = DriverTracker(
            target_fps=app_config["target_fps"],
            sliding_window_sec=app_config["window_seconds"],
            threshold_spikes=app_config["threshold_spikes"],
            config=app_config,
        )
        global_tracker = tracker
        print("[SYSTEM] SNN Tracker initialized successfully.")
        print(f"[SYSTEM] Session log: {session_logger.path}")
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
        await video_loop(tracker, args.mock, app_config["target_fps"], local_camera=args.local_camera)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] SpikeGuard stopped by user.")

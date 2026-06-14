import cv2
import numpy as np
import ctypes
import os
import math
import urllib.request

class DriverTracker:
    def __init__(self, target_fps=15, sliding_window_sec=3.0, threshold_spikes=25.0, config=None):
        self.target_fps = target_fps
        self.sliding_window_sec = sliding_window_sec
        self.threshold_spikes = threshold_spikes
        self.config = config or {}
        self.ear_threshold = float(self.config.get("ear_threshold", 0.21))
        self.mar_threshold = float(self.config.get("mar_threshold", 0.60))
        self.head_drop_seconds = float(self.config.get("head_drop_seconds", 10.0))
        self.eye_closed_seconds = float(self.config.get("eye_closed_seconds", 5.0))
        self.head_drop_started_at = None
        self.eye_closed_started_at = None
        # 1. Load SNN Engine DLL via ctypes
        self.dll_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "snn_engine.dll"))
        if not os.path.exists(self.dll_path):
            raise FileNotFoundError(f"C++ SNN DLL not found at: {self.dll_path}. Run build.bat first!")

        self.dll = ctypes.CDLL(self.dll_path)
        
        # Configure ctypes arguments and return types
        self.dll.create_snn_engine.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float]
        self.dll.create_snn_engine.restype = ctypes.c_void_p

        self.dll.destroy_snn_engine.argtypes = [ctypes.c_void_p]
        self.dll.destroy_snn_engine.restype = None

        self.dll.process_frame_dll.argtypes = [
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
        self.dll.process_frame_dll.restype = ctypes.c_int

        self.dll.reset_snn_engine.argtypes = [ctypes.c_void_p]
        self.dll.reset_snn_engine.restype = None

        # Instantiate SNN Engine in C++ heap
        self.snn_engine = self.dll.create_snn_engine(target_fps, sliding_window_sec, threshold_spikes)

        # 5-second suppression cooldown timestamp
        self.cooldown_end_time = 0.0

        # 2. Setup tracking mode
        self.use_mediapipe = False
        self.face_landmarker = None

        # Try setting up MediaPipe Tasks API
        try:
            self.setup_mediapipe()
            print("[TRACKER] MediaPipe Tasks API initialized successfully.")
        except Exception as e:
            print(f"[TRACKER] WARNING: MediaPipe initialization failed: {e}")
            print("[TRACKER] Falling back to OpenCV Haar Cascades tracking.")
            self.setup_haar_fallback()

        # Landmark Indices for EAR Calculation (MediaPipe standard indices)
        # Left eye: horizontal (33, 133), vertical (160, 144), (158, 153)
        self.LEFT_EYE_H = (33, 133)
        self.LEFT_EYE_V1 = (160, 144)
        self.LEFT_EYE_V2 = (158, 153)

        # Right eye: horizontal (362, 263), vertical (385, 380), (387, 373)
        self.RIGHT_EYE_H = (362, 263)
        self.RIGHT_EYE_V1 = (385, 380)
        self.RIGHT_EYE_V2 = (387, 373)

        self.MOUTH_H = (61, 291)
        self.MOUTH_V1 = (13, 14)
        self.MOUTH_V2 = (81, 178)

        # 3D Canonical Facial Model Points for HPE (Head Pose Estimation)
        self.HPE_INDICES = [1, 152, 33, 263, 61, 291] # Nose, Chin, L/R eye corners, L/R mouth corners
        self.model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, 330.0, 65.0),          # Chin (below nose -> positive Y, behind -> positive Z)
            (-225.0, -170.0, 135.0),     # Left eye corner (above nose -> negative Y, behind -> positive Z)
            (225.0, -170.0, 135.0),      # Right eye corner (above nose -> negative Y, behind -> positive Z)
            (-150.0, 150.0, 125.0),      # Left mouth corner (below nose -> positive Y, behind -> positive Z)
            (150.0, 150.0, 125.0)        # Right mouth corner (below nose -> positive Y, behind -> positive Z)
        ], dtype=np.float32)

    def setup_mediapipe(self):
        model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "face_landmarker.task"))
        
        # Download task model if not present
        if not os.path.exists(model_path):
            print("[TRACKER] face_landmarker.task not found. Downloading model (approx. 5.6MB)...")
            url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
            # Request timeout of 15 seconds
            urllib.request.urlretrieve(url, model_path)
            print("[TRACKER] Model downloaded successfully.")

        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        # Configure landmarker options
        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1
        )
        self.face_landmarker = vision.FaceLandmarker.create_from_options(options)
        self.use_mediapipe = True

    def setup_haar_fallback(self):
        # Find default OpenCV XML assets
        cascade_dir = os.path.dirname(cv2.__file__)
        face_xml = os.path.join(cascade_dir, 'data', 'haarcascade_frontalface_default.xml')
        eye_xml = os.path.join(cascade_dir, 'data', 'haarcascade_eye.xml')

        if not os.path.exists(face_xml) or not os.path.exists(eye_xml):
            # Try workspace fallback or absolute search
            print("[TRACKER] OpenCV cascades not found in default paths, trying download fallback...")
            # We can download them from OpenCV repo if missing
            self.download_cascade_file(face_xml, "haarcascade_frontalface_default.xml")
            self.download_cascade_file(eye_xml, "haarcascade_eye.xml")

        self.face_cascade = cv2.CascadeClassifier(face_xml)
        self.eye_cascade = cv2.CascadeClassifier(eye_xml)
        self.use_mediapipe = False
        self.closed_eyes_counter = 0
        self.baseline_y = None

    def download_cascade_file(self, dest_path, file_name):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        url = f"https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades/{file_name}"
        try:
            urllib.request.urlretrieve(url, dest_path)
            print(f"[TRACKER] Downloaded {file_name} successfully.")
        except Exception as e:
            print(f"[TRACKER] Error downloading XML: {e}")

    def __del__(self):
        if hasattr(self, 'dll') and hasattr(self, 'snn_engine'):
            self.dll.destroy_snn_engine(self.snn_engine)

    def calculate_ear(self, landmarks, indices_h, indices_v1, indices_v2, img_w, img_h):
        def get_pt(idx):
            pt = landmarks[idx]
            return np.array([pt.x * img_w, pt.y * img_h])

        h_left, h_right = get_pt(indices_h[0]), get_pt(indices_h[1])
        v1_top, v1_bottom = get_pt(indices_v1[0]), get_pt(indices_v1[1])
        v2_top, v2_bottom = get_pt(indices_v2[0]), get_pt(indices_v2[1])

        dist_h = np.linalg.norm(h_left - h_right)
        dist_v1 = np.linalg.norm(v1_top - v1_bottom)
        dist_v2 = np.linalg.norm(v2_top - v2_bottom)

        if dist_h == 0:
            return 0.0

        return float((dist_v1 + dist_v2) / (2.0 * dist_h))

    def calculate_mar(self, landmarks, img_w, img_h):
        def get_pt(idx):
            pt = landmarks[idx]
            return np.array([pt.x * img_w, pt.y * img_h])

        h_left, h_right = get_pt(self.MOUTH_H[0]), get_pt(self.MOUTH_H[1])
        v1_top, v1_bottom = get_pt(self.MOUTH_V1[0]), get_pt(self.MOUTH_V1[1])
        v2_top, v2_bottom = get_pt(self.MOUTH_V2[0]), get_pt(self.MOUTH_V2[1])

        dist_h = np.linalg.norm(h_left - h_right)
        if dist_h == 0:
            return 0.0

        dist_v1 = np.linalg.norm(v1_top - v1_bottom)
        dist_v2 = np.linalg.norm(v2_top - v2_bottom)
        return float((dist_v1 + dist_v2) / (2.0 * dist_h))

    def update_runtime_config(self, target_fps=None, sliding_window_sec=None, threshold_spikes=None, config=None):
        self.target_fps = int(target_fps or self.target_fps)
        self.sliding_window_sec = float(sliding_window_sec or self.sliding_window_sec)
        self.threshold_spikes = float(threshold_spikes or self.threshold_spikes)
        if config:
            self.config.update(config)
        self.ear_threshold = float(self.config.get("ear_threshold", self.ear_threshold))
        self.mar_threshold = float(self.config.get("mar_threshold", self.mar_threshold))
        self.head_drop_seconds = float(self.config.get("head_drop_seconds", self.head_drop_seconds))
        self.eye_closed_seconds = float(self.config.get("eye_closed_seconds", self.eye_closed_seconds))

        if getattr(self, "snn_engine", None):
            self.dll.destroy_snn_engine(self.snn_engine)
        self.snn_engine = self.dll.create_snn_engine(
            self.target_fps,
            ctypes.c_float(self.sliding_window_sec),
            ctypes.c_float(self.threshold_spikes)
        )

    def estimate_head_pose(self, landmarks, img_w, img_h):
        image_points = []
        for idx in self.HPE_INDICES:
            pt = landmarks[idx]
            image_points.append([pt.x * img_w, pt.y * img_h])
        image_points = np.array(image_points, dtype=np.float32)

        focal_length = img_w
        center = (img_w / 2.0, img_h / 2.0)
        camera_matrix = np.array([
            [focal_length, 0.0, center[0]],
            [0.0, focal_length, center[1]],
            [0.0, 0.0, 1.0]
        ], dtype=np.float32)

        dist_coeffs = np.zeros((4, 1), dtype=np.float32)

        success, rvec, tvec = cv2.solvePnP(
            self.model_points, 
            image_points, 
            camera_matrix, 
            dist_coeffs, 
            flags=cv2.SOLVEPNP_ITERATIVE
        )

        if not success:
            return 0.0, 0.0, 0.0

        rmat, _ = cv2.Rodrigues(rvec)

        sy = math.sqrt(rmat[0, 0] * rmat[0, 0] + rmat[1, 0] * rmat[1, 0])
        singular = sy < 1e-6

        if not singular:
            x = math.atan2(rmat[2, 1], rmat[2, 2])
            y = math.atan2(-rmat[2, 0], sy)
            z = math.atan2(rmat[1, 0], rmat[0, 0])
        else:
            x = math.atan2(-rmat[1, 2], rmat[1, 1])
            y = math.atan2(-rmat[2, 0], sy)
            z = 0.0

        return float(math.degrees(x)), float(math.degrees(y)), float(math.degrees(z))

    def process_snn(self, ear, pitch, yaw, roll, mar=0.0):
        import time
        spike = ctypes.c_int(0)
        accum = ctypes.c_int(0)
        state_buf = ctypes.create_string_buffer(32)
        v_memb = ctypes.c_float(0.0)

        # The C++ engine uses EAR as its event current. Keep its ABI stable and
        # translate configurable EAR/MAR risk into the equivalent low-EAR signal.
        adjusted_ear = 0.30
        if ear < self.ear_threshold:
            adjusted_ear = min(adjusted_ear, 0.21 - (self.ear_threshold - ear))
        if mar > self.mar_threshold:
            adjusted_ear = min(adjusted_ear, 0.21 - min(0.12, (mar - self.mar_threshold) * 0.6))

        self.dll.process_frame_dll(
            self.snn_engine,
            ctypes.c_float(adjusted_ear),
            ctypes.c_float(pitch),
            ctypes.c_float(yaw),
            ctypes.c_float(roll),
            ctypes.byref(spike),
            ctypes.byref(accum),
            state_buf,
            ctypes.byref(v_memb)
        )

        state = state_buf.value.decode('utf-8')
        in_cooldown = time.time() < self.cooldown_end_time
        if in_cooldown:
            state = "AWAKE"

        return {
            "spike": spike.value,
            "accumulated_spikes": accum.value,
            "state": state,
            "v_membrane": round(v_memb.value, 4),
            "in_cooldown": in_cooldown,
            "threshold": self.threshold_spikes,
            "window_seconds": self.sliding_window_sec
        }

    def apply_sustained_posture_rules(self, payload):
        import time
        metrics = payload["metrics"]
        bbox = payload["bounding_box"]
        img_h = payload["height"]
        now = time.time()

        if not payload["face_detected"] or bbox["height"] <= 0:
            self.head_drop_started_at = None
            self.eye_closed_started_at = None
            metrics["head_drop_seconds"] = 0.0
            metrics["eye_closed_seconds"] = 0.0
            metrics["head_line_y"] = round(img_h / 2.0, 1)
            payload["snn"]["head_drop_alarm"] = False
            payload["snn"]["eye_closed_alarm"] = False
            return payload

        center_y = bbox["y"] + (bbox["height"] / 2.0)
        head_line_y = img_h / 2.0
        is_dropped = center_y > head_line_y
        if is_dropped:
            if self.head_drop_started_at is None:
                self.head_drop_started_at = now
            drop_duration = now - self.head_drop_started_at
        else:
            self.head_drop_started_at = None
            drop_duration = 0.0

        eyes_closed = metrics["avg_ear"] > 0 and metrics["avg_ear"] < self.ear_threshold
        if eyes_closed:
            if self.eye_closed_started_at is None:
                self.eye_closed_started_at = now
            eye_duration = now - self.eye_closed_started_at
        else:
            self.eye_closed_started_at = None
            eye_duration = 0.0

        metrics["head_drop_seconds"] = round(drop_duration, 1)
        metrics["eye_closed_seconds"] = round(eye_duration, 1)
        metrics["head_line_y"] = round(head_line_y, 1)
        payload["snn"]["head_drop_alarm"] = drop_duration >= self.head_drop_seconds
        payload["snn"]["head_drop_threshold_seconds"] = self.head_drop_seconds
        payload["snn"]["eye_closed_alarm"] = eye_duration >= self.eye_closed_seconds
        payload["snn"]["eye_closed_threshold_seconds"] = self.eye_closed_seconds
        if payload["snn"]["head_drop_alarm"]:
            payload["snn"]["state"] = "DROWSY"
            payload["snn"]["reason"] = "HEAD_DROP_10S"
        if payload["snn"]["eye_closed_alarm"]:
            payload["snn"]["state"] = "DROWSY"
            payload["snn"]["reason"] = "EYES_CLOSED_5S"

        return payload

    def process_image(self, frame):
        img_h, img_w, _ = frame.shape
        
        # Preprocessing (Grayscale + equalization) to normalize lighting (NFR-03 compliant)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        equalized = cv2.equalizeHist(gray)

        face_detected = False
        bbox = {"x": 0, "y": 0, "width": 0, "height": 0}
        metrics = {
            "left_ear": 0.0,
            "right_ear": 0.0,
            "avg_ear": 0.0,
            "mar": 0.0,
            "hpe_pitch": 0.0,
            "hpe_yaw": 0.0,
            "hpe_roll": 0.0
        }
        
        ui_landmarks = []

        if self.use_mediapipe:
            # MediaPipe tasks API requires image in RGB
            rgb_frame = cv2.cvtColor(equalized, cv2.COLOR_GRAY2RGB)
            import mediapipe as mp
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            
            result = self.face_landmarker.detect(mp_image)

            if result.face_landmarks:
                face_detected = True
                face_landmarks = result.face_landmarks[0]

                # Calculate EAR
                left_ear = self.calculate_ear(face_landmarks, self.LEFT_EYE_H, self.LEFT_EYE_V1, self.LEFT_EYE_V2, img_w, img_h)
                right_ear = self.calculate_ear(face_landmarks, self.RIGHT_EYE_H, self.RIGHT_EYE_V1, self.RIGHT_EYE_V2, img_w, img_h)
                avg_ear = (left_ear + right_ear) / 2.0
                mar = self.calculate_mar(face_landmarks, img_w, img_h)

                # Estimate Head Pose
                pitch, yaw, roll = self.estimate_head_pose(face_landmarks, img_w, img_h)

                metrics = {
                    "left_ear": round(left_ear, 3),
                    "right_ear": round(right_ear, 3),
                    "avg_ear": round(avg_ear, 3),
                    "mar": round(mar, 3),
                    "hpe_pitch": round(pitch, 1),
                    "hpe_yaw": round(yaw, 1),
                    "hpe_roll": round(roll, 1)
                }

                # Scale coordinates to get bbox
                xs = [pt.x for pt in face_landmarks]
                ys = [pt.y for pt in face_landmarks]
                xmin, xmax = min(xs), max(xs)
                ymin, ymax = min(ys), max(ys)
                bbox = {
                    "x": int(xmin * img_w),
                    "y": int(ymin * img_h),
                    "width": int((xmax - xmin) * img_w),
                    "height": int((ymax - ymin) * img_h)
                }

                # Select a sparse list of landmarks to display on frontend overlay
                key_indices = [1, 152, 33, 133, 362, 263, 61, 291, 10, 159, 145, 386, 374]
                for idx in key_indices:
                    pt = face_landmarks[idx]
                    ui_landmarks.append({"x": int(pt.x * img_w), "y": int(pt.y * img_h)})
        else:
            # OpenCV Haar Cascades Fallback Mode
            faces = self.face_cascade.detectMultiScale(equalized, scaleFactor=1.2, minNeighbors=4, minSize=(120, 120))
            
            if len(faces) > 0:
                face_detected = True
                (x, y, w, h) = faces[0]
                bbox = {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}

                # Extract upper half of the face for eye search
                upper_y = int(y + h * 0.1)
                upper_h = int(h * 0.45)
                face_roi = equalized[upper_y:upper_y + upper_h, x:x + w]

                eyes = self.eye_cascade.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=3, minSize=(25, 25))
                
                # Check eyes detection state to calculate EAR
                avg_ear = 0.30
                mar = 0.20
                if len(eyes) >= 2:
                    self.closed_eyes_counter = 0
                    # Standard EAR from aspect ratio of detected eye box
                    eye_w = eyes[0][2]
                    eye_h = eyes[0][3]
                    avg_ear = float(eye_h) / float(eye_w)
                    if avg_ear > 0.4: avg_ear = 0.32
                else:
                    self.closed_eyes_counter += 1
                    # If eyes not detected for 3+ consecutive frames, assume closure (EAR drops to 0.08)
                    if self.closed_eyes_counter >= 3:
                        avg_ear = 0.08

                # Estimate basic Head Pose from face center shifts
                pitch, yaw, roll = 0.0, 0.0, 0.0
                face_center_y = y + h / 2.0
                if self.baseline_y is None:
                    self.baseline_y = face_center_y
                else:
                    # Nodding down (face center moves down relative to baseline)
                    diff_y = face_center_y - self.baseline_y
                    if diff_y > 25:
                        pitch = -20.0 # Nodding down
                    elif diff_y < -25:
                        pitch = 15.0 # Sleeping head back

                metrics = {
                    "left_ear": round(avg_ear, 3),
                    "right_ear": round(avg_ear, 3),
                    "avg_ear": round(avg_ear, 3),
                    "mar": round(mar, 3),
                    "hpe_pitch": round(pitch, 1),
                    "hpe_yaw": round(yaw, 1),
                    "hpe_roll": round(roll, 1)
                }

                # Construct simplified sparse landmarks
                ui_landmarks = [
                    {"x": int(x + w * 0.5), "y": int(y + h * 0.55)}, # Nose
                    {"x": int(x + w * 0.3), "y": int(y + h * 0.35)}, # Left Eye
                    {"x": int(x + w * 0.7), "y": int(y + h * 0.35)}, # Right Eye
                    {"x": int(x + w * 0.5), "y": int(y + h * 0.75)}  # Mouth
                ]

        # Feed spatial metrics into SNN
        if face_detected:
            ear = metrics["avg_ear"]
            mar = metrics["mar"]
            pitch = metrics["hpe_pitch"]
            yaw = metrics["hpe_yaw"]
            roll = metrics["hpe_roll"]
        else:
            ear = 0.30
            mar = 0.0
            pitch, yaw, roll = 0.0, 0.0, 0.0

        snn_out = self.process_snn(ear, pitch, yaw, roll, mar)

        payload = {
            "width": img_w,
            "height": img_h,
            "face_detected": face_detected,
            "bounding_box": bbox,
            "metrics": metrics,
            "snn": snn_out,
            "landmarks": ui_landmarks
        }
        return self.apply_sustained_posture_rules(payload)

    def reset_snn(self):
        import time
        self.dll.reset_snn_engine(self.snn_engine)
        self.cooldown_end_time = time.time() + 5.0
        self.head_drop_started_at = None
        self.eye_closed_started_at = None
        if not self.use_mediapipe:
            self.closed_eyes_counter = 0
            self.baseline_y = None

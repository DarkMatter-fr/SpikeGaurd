class AudioManager {
    constructor() {
        this.ctx = null;
        this.oscillator = null;
        this.gainNode = null;
        this.isPlaying = false;
        this.enabled = true;
        this.pulseTimer = null;
    }

    enable(state) {
        this.enabled = state;
        if (!state) this.stopAlarm();
    }

    startAlarm() {
        if (!this.enabled || this.isPlaying) return;
        try {
            if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
            if (this.ctx.state === "suspended") this.ctx.resume();

            this.oscillator = this.ctx.createOscillator();
            this.gainNode = this.ctx.createGain();
            this.oscillator.type = "sawtooth";
            this.oscillator.frequency.setValueAtTime(880, this.ctx.currentTime);
            this.gainNode.gain.setValueAtTime(0, this.ctx.currentTime);
            this.gainNode.gain.linearRampToValueAtTime(0.5, this.ctx.currentTime + 0.05);
            this.oscillator.connect(this.gainNode);
            this.gainNode.connect(this.ctx.destination);
            this.oscillator.start();
            this.isPlaying = true;

            this.pulseTimer = setInterval(() => {
                if (!this.ctx || !this.isPlaying) return;
                const now = this.ctx.currentTime;
                this.oscillator.frequency.setValueAtTime(880, now);
                this.oscillator.frequency.exponentialRampToValueAtTime(1100, now + 0.2);
            }, 400);
        } catch (e) {
            console.error("Audio Context Error: ", e);
        }
    }

    stopAlarm() {
        if (!this.isPlaying) return;
        if (this.pulseTimer) clearInterval(this.pulseTimer);
        this.pulseTimer = null;
        try {
            if (this.oscillator) {
                this.oscillator.stop();
                this.oscillator.disconnect();
            }
            if (this.gainNode) this.gainNode.disconnect();
        } catch (e) {
            console.error("Failed to stop oscillator safely:", e);
        }
        this.oscillator = null;
        this.gainNode = null;
        this.isPlaying = false;
    }
}

const audioManager = new AudioManager();
const earHistory = [];
const maxHistoryLength = 80;
let spikeWindowSize = 45;
let spikeHistory = new Array(spikeWindowSize).fill(0);
let ws = null;
let currentConfig = null;
let cameraStream = null;
let cameraSendTimer = null;
let alertDismissedUntilNormal = false;

const statusIndicator = document.getElementById("status-indicator");
const statusText = document.getElementById("status-text");
const noSignalPlaceholder = document.getElementById("no-signal");
const videoStream = document.getElementById("video-stream");
const landmarkCanvas = document.getElementById("landmark-canvas");
const canvasCtx = landmarkCanvas.getContext("2d");
const localCameraPreview = document.getElementById("local-camera-preview");
const cameraCaptureCanvas = document.getElementById("camera-capture-canvas");
const cameraTitle = document.getElementById("camera-title");
const cameraError = document.getElementById("camera-error");
const faceStatus = document.getElementById("face-status");
const systemState = document.getElementById("system-state");
const alarmOverlay = document.getElementById("alarm-overlay");
const vmValue = document.getElementById("vm-value");
const vmBar = document.getElementById("vm-bar");
const spikeRateText = document.getElementById("spike-rate");
const spikeRaster = document.getElementById("spike-raster");
const accumulatedSpikes = document.getElementById("accumulated-spikes");
const spikeThreshold = document.getElementById("spike-threshold");
const thresholdBar = document.getElementById("threshold-bar");
const earValue = document.getElementById("ear-value");
const marValue = document.getElementById("mar-value");
const marThresholdLabel = document.getElementById("mar-threshold-label");
const hpePitch = document.getElementById("hpe-pitch");
const hpeYaw = document.getElementById("hpe-yaw");
const hpeRoll = document.getElementById("hpe-roll");
const headDropTimer = document.getElementById("head-drop-timer");
const eyeClosedTimer = document.getElementById("eye-closed-timer");
const fpsBadge = document.getElementById("fps-badge");
const spikeWindowLabel = document.getElementById("spike-window-label");
const btnSoundToggle = document.getElementById("btn-sound-toggle");
const btnReset = document.getElementById("btn-reset");
const btnDismissAlarm = document.getElementById("btn-dismiss-alarm");
const btnSaveConfig = document.getElementById("btn-save-config");
const btnStartCamera = document.getElementById("btn-start-camera");
const btnUseDemo = document.getElementById("btn-use-demo");
const presetSelect = document.getElementById("preset-select");
const earThresholdInput = document.getElementById("ear-threshold-input");
const windowInput = document.getElementById("window-input");
const thresholdInput = document.getElementById("threshold-input");
const configSaveStatus = document.getElementById("config-save-status");
const sessionEventCount = document.getElementById("session-event-count");
const sessionAvgDuration = document.getElementById("session-avg-duration");
const sessionLogPath = document.getElementById("session-log-path");

function applyConfigToUi(config) {
    const previousWindowSize = spikeWindowSize;
    currentConfig = config;
    presetSelect.value = config.preset || "standard";
    earThresholdInput.value = Number(config.ear_threshold || 0.21).toFixed(2);
    windowInput.value = Number(config.window_seconds || 3.0).toFixed(1);
    thresholdInput.value = Number(config.threshold_spikes || 25).toFixed(0);
    spikeThreshold.textContent = Number(config.threshold_spikes || 25).toFixed(0);
    marThresholdLabel.textContent = Number(config.mar_threshold || 0.60).toFixed(2);
    fpsBadge.textContent = `${config.target_fps || 15} FPS TARGET`;
    spikeWindowLabel.textContent = `TEMPORAL SPIKE TRAIN (${config.window_seconds || 3}S WINDOW)`;
    spikeWindowSize = Math.max(1, Math.round((config.target_fps || 15) * (config.window_seconds || 3)));
    if (spikeWindowSize !== previousWindowSize || spikeHistory.length !== spikeWindowSize) {
        spikeHistory = new Array(spikeWindowSize).fill(0);
        renderSpikeRaster();
    }
}

async function loadConfig() {
    try {
        const response = await fetch("/api/config");
        if (response.ok) applyConfigToUi(await response.json());
    } catch (e) {
        console.warn("Unable to load config", e);
    }
}

async function loadSummary() {
    try {
        const response = await fetch("/api/summary");
        if (!response.ok) return;
        const summary = await response.json();
        sessionEventCount.textContent = summary.event_count || 0;
        sessionAvgDuration.textContent = `${Number(summary.average_alert_duration || 0).toFixed(2)}s`;
        sessionLogPath.textContent = summary.log_path || "Log pending";
    } catch (e) {
        console.warn("Unable to load summary", e);
    }
}

function sendReset() {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ command: "reset" }));
    earHistory.length = 0;
    spikeHistory.fill(0);
    audioManager.stopAlarm();
    alarmOverlay.classList.add("hidden");
    renderSpikeRaster();
    loadSummary();
}

function dismissCurrentAlert() {
    alertDismissedUntilNormal = true;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ command: "dismiss" }));
    audioManager.stopAlarm();
    alarmOverlay.classList.add("hidden");
    loadSummary();
}

function getWebSocketUrl() {
    return `ws://${window.location.hostname || "localhost"}:8765`;
}

function beginCameraFramePump() {
    if (cameraSendTimer) clearInterval(cameraSendTimer);
    const fps = Math.min(30, Math.max(5, currentConfig?.target_fps || 15));
    const interval = Math.round(1000 / fps);
    cameraSendTimer = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !cameraStream) return;
        if (localCameraPreview.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;

        const sourceWidth = localCameraPreview.videoWidth || 640;
        const sourceHeight = localCameraPreview.videoHeight || 480;
        const scale = Math.min(1, 640 / sourceWidth);
        const width = Math.round(sourceWidth * scale);
        const height = Math.round(sourceHeight * scale);
        cameraCaptureCanvas.width = width;
        cameraCaptureCanvas.height = height;
        const ctx = cameraCaptureCanvas.getContext("2d");
        ctx.drawImage(localCameraPreview, 0, 0, width, height);
        const frame = cameraCaptureCanvas.toDataURL("image/jpeg", 0.55);
        ws.send(JSON.stringify({ type: "camera_frame", frame }));
    }, interval);
}

async function startBrowserCamera() {
    cameraError.textContent = "";
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        cameraError.textContent = "This browser does not expose camera permission APIs.";
        return;
    }

    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                facingMode: "user"
            },
            audio: false
        });
        localCameraPreview.srcObject = cameraStream;
        await localCameraPreview.play();
        noSignalPlaceholder.classList.add("hidden");
        localCameraPreview.classList.remove("hidden");
        cameraTitle.textContent = "Live browser camera";
        beginCameraFramePump();
    } catch (e) {
        cameraError.textContent = e && e.name === "NotAllowedError"
            ? "Camera permission was denied. Allow camera access in the browser to use live monitoring."
            : "Unable to start the camera. Check that no other app is using it.";
    }
}

btnSoundToggle.addEventListener("click", () => {
    const nextState = !audioManager.enabled;
    audioManager.enable(nextState);
    btnSoundToggle.classList.toggle("active", nextState);
    btnSoundToggle.classList.toggle("inactive", !nextState);
    btnSoundToggle.querySelector(".btn-icon").textContent = nextState ? "AUDIO" : "MUTED";
    btnSoundToggle.querySelector(".btn-text").textContent = nextState ? "AUDIO ALERTS ENABLED" : "AUDIO ALERTS DISABLED";
});

btnReset.addEventListener("click", sendReset);
btnDismissAlarm.addEventListener("click", dismissCurrentAlert);
document.addEventListener("keydown", (event) => {
    if (event.code === "Space") {
        event.preventDefault();
        dismissCurrentAlert();
    }
});

btnSaveConfig.addEventListener("click", async () => {
    configSaveStatus.textContent = "SAVING";
    try {
        const response = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                preset: presetSelect.value,
                ear_threshold: Number(earThresholdInput.value),
                window_seconds: Number(windowInput.value),
                threshold_spikes: Number(thresholdInput.value)
            })
        });
        if (!response.ok) throw new Error("Config save failed");
        applyConfigToUi(await response.json());
        configSaveStatus.textContent = "SAVED";
        setTimeout(() => configSaveStatus.textContent = "READY", 1600);
    } catch (e) {
        console.error(e);
        configSaveStatus.textContent = "ERROR";
    }
});

btnStartCamera.addEventListener("click", startBrowserCamera);
btnUseDemo.addEventListener("click", () => {
    cameraError.textContent = "Mock demo runs when the backend is started with: python src\\main.py --mock";
});

function renderSpikeRaster() {
    spikeRaster.innerHTML = "";
    for (let i = 0; i < spikeWindowSize; i++) {
        const node = document.createElement("div");
        node.classList.add("spike-node");
        if (spikeHistory[i] === 1) node.classList.add("active");
        spikeRaster.appendChild(node);
    }
}

function drawEarChart(newEar) {
    earHistory.push(newEar);
    if (earHistory.length > maxHistoryLength) earHistory.shift();

    const canvas = document.getElementById("ear-chart");
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    [0.1, 0.2, 0.3].forEach((val) => {
        const y = h - (val / 0.4) * h;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    });

    const threshold = currentConfig?.ear_threshold || 0.21;
    const threshY = h - (threshold / 0.4) * h;
    ctx.strokeStyle = "rgba(255, 51, 51, 0.45)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, threshY);
    ctx.lineTo(w, threshY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = newEar < threshold ? "#ff3333" : "#00e676";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    earHistory.forEach((val, i) => {
        const x = (i / Math.max(1, maxHistoryLength - 1)) * w;
        const y = h - (val / 0.4) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}

function drawOverlay(payload) {
    const visualTarget = payload.source === "browser_camera" ? localCameraPreview : videoStream;
    const rect = visualTarget.getBoundingClientRect();
    const w = landmarkCanvas.width = rect.width;
    const h = landmarkCanvas.height = rect.height;
    canvasCtx.clearRect(0, 0, w, h);
    canvasCtx.save();
    canvasCtx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    canvasCtx.lineWidth = 2;
    canvasCtx.setLineDash([8, 8]);
    canvasCtx.beginPath();
    canvasCtx.moveTo(0, h / 2);
    canvasCtx.lineTo(w, h / 2);
    canvasCtx.stroke();
    canvasCtx.setLineDash([]);
    canvasCtx.fillStyle = "rgba(255, 255, 255, 0.82)";
    canvasCtx.font = "700 12px Inter, sans-serif";
    canvasCtx.fillText("HEAD DROP LINE", 14, (h / 2) - 10);
    canvasCtx.restore();
    if (!payload.face_detected) return;

    const origW = payload.width || 640;
    const origH = payload.height || 480;
    const scaleX = w / origW;
    const scaleY = h / origH;
    const bbox = payload.bounding_box;
    const bx = bbox.x * scaleX;
    const by = bbox.y * scaleY;
    const bw = bbox.width * scaleX;
    const bh = bbox.height * scaleY;

    canvasCtx.strokeStyle = payload.snn.state === "DROWSY" ? "#ff3333" : "#00d2ff";
    canvasCtx.lineWidth = 2;
    canvasCtx.strokeRect(bx, by, bw, bh);
    canvasCtx.fillStyle = payload.snn.state === "DROWSY" ? "rgba(255, 51, 51, 0.8)" : "rgba(0, 230, 118, 0.8)";
    payload.landmarks.forEach((pt) => {
        canvasCtx.beginPath();
        canvasCtx.arc(pt.x * scaleX, pt.y * scaleY, 2.5, 0, 2 * Math.PI);
        canvasCtx.fill();
    });
}

function updateTelemetry(payload) {
    if (payload.config && JSON.stringify(payload.config) !== JSON.stringify(currentConfig)) {
        applyConfigToUi({ ...currentConfig, ...payload.config });
    }
    if (payload.frame) {
        videoStream.src = payload.frame;
        videoStream.classList.remove("hidden");
        localCameraPreview.classList.add("hidden");
        noSignalPlaceholder.classList.add("hidden");
    } else if (payload.source === "browser_camera") {
        videoStream.classList.add("hidden");
        localCameraPreview.classList.remove("hidden");
        noSignalPlaceholder.classList.add("hidden");
    }
    drawOverlay(payload);

    const metrics = payload.metrics || {};
    if (payload.face_detected) {
        faceStatus.textContent = "LOCKED";
        faceStatus.className = "val normal";
        earValue.textContent = Number(metrics.avg_ear || 0).toFixed(3);
        earValue.className = (metrics.avg_ear || 0) < (currentConfig?.ear_threshold || 0.21) ? "lcd-text red" : "lcd-text green";
        marValue.textContent = Number(metrics.mar || 0).toFixed(3);
        marValue.className = (metrics.mar || 0) > (currentConfig?.mar_threshold || 0.60) ? "lcd-text red" : "lcd-text green";
        hpePitch.textContent = `${Number(metrics.hpe_pitch || 0).toFixed(1)} deg`;
        hpeYaw.textContent = `${Number(metrics.hpe_yaw || 0).toFixed(1)} deg`;
        hpeRoll.textContent = `${Number(metrics.hpe_roll || 0).toFixed(1)} deg`;
        hpePitch.className = (metrics.hpe_pitch || 0) < -12 ? "val danger" : "val neutral";
        hpeYaw.className = Math.abs(metrics.hpe_yaw || 0) > 20 ? "val danger" : "val neutral";
        hpeRoll.className = Math.abs(metrics.hpe_roll || 0) > 18 ? "val danger" : "val neutral";
        const dropDuration = Number(metrics.head_drop_seconds || 0);
        const dropThreshold = Number(payload.snn?.head_drop_threshold_seconds || 10);
        headDropTimer.textContent = `${dropDuration.toFixed(1)}s / ${dropThreshold.toFixed(1)}s`;
        headDropTimer.className = payload.snn?.head_drop_alarm ? "val danger" : (dropDuration > 0 ? "val warn" : "val neutral");
        const eyeDuration = Number(metrics.eye_closed_seconds || 0);
        const eyeThreshold = Number(payload.snn?.eye_closed_threshold_seconds || 5);
        eyeClosedTimer.textContent = `${eyeDuration.toFixed(1)}s / ${eyeThreshold.toFixed(1)}s`;
        eyeClosedTimer.className = payload.snn?.eye_closed_alarm ? "val danger" : (eyeDuration > 0 ? "val warn" : "val neutral");
        drawEarChart(metrics.avg_ear || 0);
    } else {
        faceStatus.textContent = "LOST";
        faceStatus.className = "val danger";
        headDropTimer.textContent = "0.0s / 10.0s";
        headDropTimer.className = "val neutral";
        eyeClosedTimer.textContent = "0.0s / 5.0s";
        eyeClosedTimer.className = "val neutral";
        drawEarChart(0.30);
    }

    const snn = payload.snn || {};
    const state = snn.state || "AWAKE";
    const activeSustainedCondition = Number(metrics.head_drop_seconds || 0) > 0 || Number(metrics.eye_closed_seconds || 0) > 0;
    if (state !== "DROWSY" && !activeSustainedCondition) {
        alertDismissedUntilNormal = false;
    }
    systemState.textContent = snn.in_cooldown ? "COOLDOWN" : state;
    systemState.className = snn.in_cooldown ? "val warn" : (state === "DROWSY" ? "val danger" : "val normal");
    vmValue.textContent = Number(snn.v_membrane || 0).toFixed(4);
    vmBar.style.width = `${Math.min(100, Number(snn.v_membrane || 0) * 100)}%`;

    spikeHistory.push(snn.spike || 0);
    if (spikeHistory.length > spikeWindowSize) spikeHistory.shift();
    renderSpikeRaster();

    const threshold = Number(snn.threshold || currentConfig?.threshold_spikes || 25);
    const accum = Number(snn.accumulated_spikes || 0);
    spikeThreshold.textContent = threshold.toFixed(0);
    accumulatedSpikes.textContent = accum;
    thresholdBar.style.width = `${Math.min(100, (accum / threshold) * 100)}%`;
    thresholdBar.style.background = accum >= threshold ? "#ff3333" : "#ffb300";
    spikeRateText.textContent = `${accum} spikes`;

    if (state === "DROWSY" && !alertDismissedUntilNormal) {
        alarmOverlay.classList.remove("hidden");
        audioManager.startAlarm();
    } else {
        alarmOverlay.classList.add("hidden");
        audioManager.stopAlarm();
    }
}

function connectWebSocket() {
    ws = new WebSocket(getWebSocketUrl());
    ws.onopen = () => {
        statusIndicator.className = "connection-pill connected";
        statusText.textContent = "Connected";
        if (cameraStream) beginCameraFramePump();
    };
    ws.onmessage = (event) => {
        updateTelemetry(JSON.parse(event.data));
        loadSummary();
    };
    ws.onclose = () => {
        statusIndicator.className = "connection-pill disconnected";
        statusText.textContent = "Offline";
        videoStream.classList.add("hidden");
        noSignalPlaceholder.classList.remove("hidden");
        audioManager.stopAlarm();
        alarmOverlay.classList.add("hidden");
        if (cameraSendTimer) clearInterval(cameraSendTimer);
        setTimeout(connectWebSocket, 3000);
    };
    ws.onerror = (err) => console.error("WebSocket Error:", err);
}

renderSpikeRaster();
loadConfig();
loadSummary();
setInterval(loadSummary, 5000);
connectWebSocket();

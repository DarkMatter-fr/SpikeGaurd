// AudioManager handles generating the alert buzzer using browser native Web Audio API
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
        if (!state) {
            this.stopAlarm();
        }
    }

    startAlarm() {
        if (!this.enabled || this.isPlaying) return;

        try {
            // Lazy initialization of AudioContext on user interaction
            if (!this.ctx) {
                this.ctx = new (window.AudioContext || window.webkitAudioContext)();
            }

            if (this.ctx.state === 'suspended') {
                this.ctx.resume();
            }

            this.oscillator = this.ctx.createOscillator();
            this.gainNode = this.ctx.createGain();

            // Sawtooth wave for a harsh alarm tone
            this.oscillator.type = 'sawtooth';
            this.oscillator.frequency.setValueAtTime(880, this.ctx.currentTime); // A5 note

            // Set initial volume
            this.gainNode.gain.setValueAtTime(0, this.ctx.currentTime);
            this.gainNode.gain.linearRampToValueAtTime(0.5, this.ctx.currentTime + 0.05);

            this.oscillator.connect(this.gainNode);
            this.gainNode.connect(this.ctx.destination);

            this.oscillator.start();
            this.isPlaying = true;

            // Pulsing frequency effect (Siren)
            this.pulseTimer = setInterval(() => {
                if (this.ctx && this.isPlaying) {
                    const now = this.ctx.currentTime;
                    // Pulse pitch back and forth between 880Hz and 1100Hz
                    this.oscillator.frequency.setValueAtTime(880, now);
                    this.oscillator.frequency.exponentialRampToValueAtTime(1100, now + 0.2);
                }
            }, 400);

        } catch (e) {
            console.error("Audio Context Error: ", e);
        }
    }

    stopAlarm() {
        if (!this.isPlaying) return;

        if (this.pulseTimer) {
            clearInterval(this.pulseTimer);
            this.pulseTimer = null;
        }

        try {
            if (this.oscillator) {
                this.oscillator.stop();
                this.oscillator.disconnect();
                this.oscillator = null;
            }
            if (this.gainNode) {
                this.gainNode.disconnect();
                this.gainNode = null;
            }
        } catch (e) {
            console.error("Failed to stop oscillator safely:", e);
        }

        this.isPlaying = false;
    }
}

// Instantiate Audio controller
const audioManager = new AudioManager();

// Global telemetry buffers
const earHistory = [];
const maxHistoryLength = 80;
const spikeWindowSize = 45; // 3 seconds at 15 FPS
let spikeHistory = new Array(spikeWindowSize).fill(0);

// Initialize UI Elements
const statusIndicator = document.getElementById("status-indicator");
const statusText = document.getElementById("status-text");
const noSignalPlaceholder = document.getElementById("no-signal");
const videoStream = document.getElementById("video-stream");
const landmarkCanvas = document.getElementById("landmark-canvas");
const canvasCtx = landmarkCanvas.getContext("2d");

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
const hpePitch = document.getElementById("hpe-pitch");
const hpeYaw = document.getElementById("hpe-yaw");
const hpeRoll = document.getElementById("hpe-roll");

const btnSoundToggle = document.getElementById("btn-sound-toggle");
const btnReset = document.getElementById("btn-reset");
const btnDismissAlarm = document.getElementById("btn-dismiss-alarm");

// Sound Toggle Interaction
btnSoundToggle.addEventListener("click", () => {
    if (audioManager.enabled) {
        audioManager.enable(false);
        btnSoundToggle.classList.remove("active");
        btnSoundToggle.classList.add("inactive");
        btnSoundToggle.querySelector(".btn-icon").textContent = "🔇";
        btnSoundToggle.querySelector(".btn-text").textContent = "AUDIO ALERTS DISABLED";
    } else {
        // Resume context on user click
        audioManager.enable(true);
        btnSoundToggle.classList.remove("inactive");
        btnSoundToggle.classList.add("active");
        btnSoundToggle.querySelector(".btn-icon").textContent = "🔊";
        btnSoundToggle.querySelector(".btn-text").textContent = "AUDIO ALERTS ENABLED";
    }
});

// Reset Button Interface
btnReset.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        // Send reset signal
        ws.send(JSON.stringify({ "command": "reset" }));
    }
    // Clean front-end state
    earHistory.length = 0;
    spikeHistory.fill(0);
    audioManager.stopAlarm();
    alarmOverlay.classList.add("hidden");
    renderSpikeRaster();
});

// Dismiss Alarm Button Interface
btnDismissAlarm.addEventListener("click", () => {
    // Silence alarm immediately on front-end
    audioManager.stopAlarm();
    alarmOverlay.classList.add("hidden");
    
    // Send reset command to backend
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ "command": "reset" }));
    }
    
    // Reset local spike train visualizer
    spikeHistory.fill(0);
    renderSpikeRaster();
});

// Render the 3S sliding window spike raster
function renderSpikeRaster() {
    spikeRaster.innerHTML = "";
    for (let i = 0; i < spikeWindowSize; i++) {
        const node = document.createElement("div");
        node.classList.add("spike-node");
        if (spikeHistory[i] === 1) {
            node.classList.add("active");
        } else if (spikeHistory[i] === -1) {
            node.classList.add("inactive"); // Default placeholder
        }
        spikeRaster.appendChild(node);
    }
}
renderSpikeRaster();

// Draw historical EAR trend
function drawEarChart(newEar) {
    earHistory.push(newEar);
    if (earHistory.length > maxHistoryLength) {
        earHistory.shift();
    }

    const canvas = document.getElementById("ear-chart");
    const ctx = canvas.getContext("2d");
    
    // Handle retina display crispness
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    // Draw background horizontal reference lines (0.1, 0.2, 0.3)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    const levels = [0.1, 0.2, 0.3];
    levels.forEach(val => {
        const y = h - (val / 0.4) * h;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    });

    // Draw EAR threshold line (0.21)
    const threshY = h - (0.21 / 0.4) * h;
    ctx.strokeStyle = "rgba(255, 51, 51, 0.45)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, threshY);
    ctx.lineTo(w, threshY);
    ctx.stroke();
    ctx.setLineDash([]); // Reset dash

    if (earHistory.length === 0) return;

    // Draw EAR trendline path
    ctx.strokeStyle = newEar < 0.21 ? "#ff3333" : "#00e676";
    ctx.shadowColor = newEar < 0.21 ? "rgba(255, 51, 51, 0.4)" : "rgba(0, 230, 118, 0.2)";
    ctx.shadowBlur = 4;
    ctx.lineWidth = 2.5;
    ctx.beginPath();

    for (let i = 0; i < earHistory.length; i++) {
        const x = (i / (maxHistoryLength - 1)) * w;
        const val = earHistory[i];
        const y = h - (val / 0.4) * h;
        
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    }
    ctx.stroke();
    ctx.shadowBlur = 0; // Reset shadows
}

// Draw bounding box and landmarks
function drawOverlay(payload) {
    const rect = videoStream.getBoundingClientRect();
    const w = landmarkCanvas.width = rect.width;
    const h = landmarkCanvas.height = rect.height;
    canvasCtx.clearRect(0, 0, w, h);

    if (!payload.face_detected) return;

    // Bounding Box Scaling based on dynamic source resolution
    const origW = payload.width || 640.0;
    const origH = payload.height || 480.0;
    const scaleX = w / origW;
    const scaleY = h / origH;

    const bbox = payload.bounding_box;
    const bx = bbox.x * scaleX;
    const by = bbox.y * scaleY;
    const bw = bbox.width * scaleX;
    const bh = bbox.height * scaleY;

    // Draw Face Border
    canvasCtx.strokeStyle = payload.snn.state === "DROWSY" ? "#ff3333" : "#00d2ff";
    canvasCtx.lineWidth = 2;
    canvasCtx.strokeRect(bx, by, bw, bh);

    // Draw Selected Facial landmarks
    canvasCtx.fillStyle = payload.snn.state === "DROWSY" ? "rgba(255, 51, 51, 0.8)" : "rgba(0, 230, 118, 0.8)";
    payload.landmarks.forEach(pt => {
        const px = pt.x * scaleX;
        const py = pt.y * scaleY;
        canvasCtx.beginPath();
        canvasCtx.arc(px, py, 2.5, 0, 2 * Math.PI);
        canvasCtx.fill();
    });

    // Draw 3D Coordinate Axes Gnomon from Nose Tip
    if (payload.landmarks.length > 0) {
        const nose = payload.landmarks[0];
        const nx = nose.x * scaleX;
        const ny = nose.y * scaleY;

        const pitch = payload.metrics.hpe_pitch;
        const yaw = payload.metrics.hpe_yaw;
        const roll = payload.metrics.hpe_roll;

        const axisLength = 50;
        const radPitch = (pitch * Math.PI) / 180;
        const radYaw = (yaw * Math.PI) / 180;
        const radRoll = (roll * Math.PI) / 180;

        // 1. Z-axis (Forward pointer - Yellow/Orange)
        const zx = nx + axisLength * Math.sin(radYaw) * Math.cos(radPitch);
        const zy = ny - axisLength * Math.sin(radPitch);

        canvasCtx.strokeStyle = "#ffb300";
        canvasCtx.lineWidth = 3;
        canvasCtx.beginPath();
        canvasCtx.moveTo(nx, ny);
        canvasCtx.lineTo(zx, zy);
        canvasCtx.stroke();
        
        canvasCtx.fillStyle = "#ffb300";
        canvasCtx.beginPath();
        canvasCtx.arc(zx, zy, 4, 0, 2 * Math.PI);
        canvasCtx.fill();

        // 2. X-axis (Sideways Right - Red)
        const xx = nx + axisLength * Math.cos(radYaw) * Math.cos(radRoll);
        const xy = ny + axisLength * Math.sin(radRoll);
        canvasCtx.strokeStyle = "rgba(255, 51, 51, 0.6)";
        canvasCtx.lineWidth = 1.5;
        canvasCtx.beginPath();
        canvasCtx.moveTo(nx, ny);
        canvasCtx.lineTo(xx, xy);
        canvasCtx.stroke();

        // 3. Y-axis (Sideways Down - Green)
        const yx = nx - axisLength * Math.sin(radRoll);
        const yy = ny + axisLength * Math.cos(radPitch) * Math.cos(radRoll);
        canvasCtx.strokeStyle = "rgba(0, 230, 118, 0.6)";
        canvasCtx.lineWidth = 1.5;
        canvasCtx.beginPath();
        canvasCtx.moveTo(nx, ny);
        canvasCtx.lineTo(yx, yy);
        canvasCtx.stroke();
    }
}

// Setup WebSocket Connection
let ws = null;
function connectWebSocket() {
    console.log("Connecting to SpikeGuard WebSocket server...");
    ws = new WebSocket("ws://localhost:8765");

    ws.onopen = () => {
        console.log("WebSocket Connection Established.");
        statusIndicator.className = "connected";
        statusText.textContent = "CONNECTED";
    };

    ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);

        // Render Frame
        if (payload.frame) {
            videoStream.src = payload.frame;
            if (videoStream.classList.contains("hidden")) {
                videoStream.classList.remove("hidden");
                noSignalPlaceholder.classList.add("hidden");
            }
        }

        // Draw HUD Overlays
        drawOverlay(payload);

        // Update Biometric Metrics
        if (payload.face_detected) {
            faceStatus.textContent = "LOCKED";
            faceStatus.className = "val normal";
            
            earValue.textContent = payload.metrics.avg_ear.toFixed(3);
            earValue.className = payload.metrics.avg_ear < 0.21 ? "lcd-text red" : "lcd-text green";

            hpePitch.textContent = `${payload.metrics.hpe_pitch > 0 ? '+' : ''}${payload.metrics.hpe_pitch.toFixed(1)}°`;
            hpePitch.className = payload.metrics.hpe_pitch < -12 ? "val danger" : "val neutral";

            hpeYaw.textContent = `${payload.metrics.hpe_yaw > 0 ? '+' : ''}${payload.metrics.hpe_yaw.toFixed(1)}°`;
            hpeYaw.className = Math.abs(payload.metrics.hpe_yaw) > 20 ? "val danger" : "val neutral";

            hpeRoll.textContent = `${payload.metrics.hpe_roll > 0 ? '+' : ''}${payload.metrics.hpe_roll.toFixed(1)}°`;
            hpeRoll.className = Math.abs(payload.metrics.hpe_roll) > 18 ? "val danger" : "val neutral";
            
            drawEarChart(payload.metrics.avg_ear);
        } else {
            faceStatus.textContent = "LOST";
            faceStatus.className = "val danger";
            earValue.textContent = "0.000";
            earValue.className = "lcd-text";
            
            hpePitch.textContent = "0.0°";
            hpePitch.className = "val neutral";
            hpeYaw.textContent = "0.0°";
            hpeYaw.className = "val neutral";
            hpeRoll.textContent = "0.0°";
            hpeRoll.className = "val neutral";
            
            drawEarChart(0.30); // Default flat alert EAR
        }

        // Update SNN Inferece state
        const state = payload.snn.state;
        const inCooldown = payload.snn.in_cooldown;

        if (inCooldown) {
            systemState.textContent = "COOLDOWN";
            systemState.className = "val warn";
        } else {
            systemState.textContent = state;
            systemState.className = state === "DROWSY" ? "val danger" : "val normal";
        }

        const vm = payload.snn.v_membrane;
        vmValue.textContent = vm.toFixed(4);
        vmBar.style.width = `${Math.min(100, vm * 100)}%`;
        if (vm >= 0.8) {
            vmBar.style.background = "linear-gradient(90deg, #ffb300 0%, #ff3333 100%)";
        } else {
            vmBar.style.background = "linear-gradient(90deg, #00d2ff 0%, #0066ff 100%)";
        }

        // Update Spike sliding window buffer
        const spike = payload.snn.spike;
        spikeHistory.push(spike);
        if (spikeHistory.length > spikeWindowSize) {
            spikeHistory.shift();
        }
        renderSpikeRaster();

        // Update Spikes Accumulator
        const thresh = payload.snn.threshold || 25.0; // SNN spike threshold
        spikeThreshold.textContent = thresh;
        
        const accum = payload.snn.accumulated_spikes;
        accumulatedSpikes.textContent = accum;
        
        const fillPerc = Math.min(100, (accum / thresh) * 100);
        thresholdBar.style.width = `${fillPerc}%`;
        if (accum >= thresh) {
            thresholdBar.style.background = "#ff3333";
        } else {
            thresholdBar.style.background = "#ffb300";
        }

        const spikeCount = spikeHistory.filter(s => s === 1).length;
        spikeRateText.textContent = `${accum} spikes`;

        // Handle State Alarm Triggers
        if (state === "DROWSY") {
            alarmOverlay.classList.remove("hidden");
            audioManager.startAlarm();
        } else {
            alarmOverlay.classList.add("hidden");
            audioManager.stopAlarm();
        }
    };

    ws.onclose = () => {
        console.log("WebSocket Connection Closed. Attempting reconnect...");
        statusIndicator.className = "disconnected";
        statusText.textContent = "OFFLINE";
        
        videoStream.classList.add("hidden");
        noSignalPlaceholder.classList.remove("hidden");
        
        audioManager.stopAlarm();
        alarmOverlay.classList.add("hidden");

        // Attempt reconnection in 3 seconds
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (err) => {
        console.error("WebSocket Error:", err);
    };
}

// Start WebSocket Connection Loop
connectWebSocket();

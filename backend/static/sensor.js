// SANS — celular sensor.
// Microfone -> reamostra p/ 16 kHz -> YAMNet (TensorFlow.js, roda no celular)
// -> evento JSON -> Flask grava e avisa o ESP32 -> painel.

// Eventos do SANS e as classes do YAMNet que os representam (índices do
// yamnet_class_map.csv). A confiança do evento é a MAIOR pontuação real entre
// as classes listadas.
const EVENTS = {
  doorbell:    { label: "Campainha",         classes: [349, 350] },        // Doorbell, Ding-dong
  dog_barking: { label: "Cachorro latindo",  classes: [69, 70] },          // Dog, Bark
  cat_meowing: { label: "Miado de gato",     classes: [76, 78] },          // Cat, Meow
  clapping:    { label: "Palmas",            classes: [58, 62] },          // Clapping, Applause
  alarm:       { label: "Alarme",            classes: [382, 389, 390, 391, 393, 394] },
};

const SAMPLE_RATE = 16000;
const WINDOW = 15600;          // ~0,975 s: tamanho que o YAMNet espera
const HOP = 7680;              // roda a cada ~0,48 s
const CONFIRMATIONS = 2;       // janelas seguidas acima do limite antes de enviar
const COOLDOWN_MS = 10000;     // não repete o mesmo evento por 10 s

const MODEL_URL = "https://tfhub.dev/google/tfjs-model/yamnet/tfjs/1";
const TF_URL = "https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js";

const $ = (id) => document.getElementById(id);
const toggleBtn = $("toggle");
const statusEl = $("status");
const statusText = $("status-text");
const levelEl = $("level");
const thresholdEl = $("threshold");

let model = null;
let classNames = [];
let audioCtx = null;
let stream = null;
let processor = null;
let wakeLock = null;
let running = false;
let busy = false;

const ring = new Float32Array(WINDOW);
let filled = 0;
let writeIdx = 0;
let pending = 0;
const hits = {};
const lastSent = {};

function setStatus(state, text) {
  statusEl.dataset.state = state;
  statusText.textContent = text;
}

function threshold() {
  return Number(thresholdEl.value) / 100;
}

thresholdEl.addEventListener("input", () => {
  $("threshold-value").textContent = `${thresholdEl.value}%`;
});

// ---------- carregamento ----------
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(src));
    document.head.append(s);
  });
}

async function ensureTf() {
  if (window.tf) return;
  await loadScript(TF_URL);
  if (!window.tf) throw new Error("O TensorFlow.js não iniciou.");
}

async function ensureModel() {
  if (model) return;
  await ensureTf();
  model = await tf.loadGraphModel(MODEL_URL, { fromTFHub: true });
}

async function loadClassNames() {
  if (classNames.length) return;
  const text = await (await fetch("/static/yamnet_class_map.csv")).text();
  for (const line of text.split(/\r?\n/).slice(1)) {
    if (!line.trim()) continue;
    const first = line.indexOf(",");
    const second = line.indexOf(",", first + 1);
    const index = Number(line.slice(0, first));
    classNames[index] = line.slice(second + 1).replace(/^"|"$/g, "");
  }
}

// ---------- áudio ----------
class Resampler {
  constructor(inRate, outRate) {
    this.ratio = inRate / outRate;
    this.buf = new Float32Array(0);
    this.pos = 0;
  }
  push(chunk) {
    const merged = new Float32Array(this.buf.length + chunk.length);
    merged.set(this.buf);
    merged.set(chunk, this.buf.length);
    this.buf = merged;
    const out = [];
    while (this.pos + this.ratio <= this.buf.length) {
      const start = Math.floor(this.pos);
      const end = Math.max(start + 1, Math.floor(this.pos + this.ratio));
      let sum = 0;
      for (let i = start; i < end; i++) sum += this.buf[i];
      out.push(sum / (end - start));
      this.pos += this.ratio;
    }
    const drop = Math.floor(this.pos);
    this.buf = this.buf.slice(drop);
    this.pos -= drop;
    return out;
  }
}

function pushSamples(samples) {
  for (const s of samples) {
    ring[writeIdx] = s;
    writeIdx = (writeIdx + 1) % WINDOW;
  }
  filled = Math.min(WINDOW, filled + samples.length);
  pending += samples.length;
}

function latestWindow() {
  const out = new Float32Array(WINDOW);
  for (let i = 0; i < WINDOW; i++) out[i] = ring[(writeIdx + i) % WINDOW];
  return out;
}

// ---------- classificação ----------
async function classify() {
  busy = true;
  try {
    const input = tf.tensor1d(latestWindow());
    const outputs = model.predict(input);
    const scoresTensor = Array.isArray(outputs) ? outputs[0] : outputs;
    const mean = scoresTensor.mean(0);
    const scores = await mean.data();
    input.dispose();
    mean.dispose();
    (Array.isArray(outputs) ? outputs : [outputs]).forEach((t) => t.dispose());
    handleScores(scores);
  } catch (error) {
    setStatus("error", `Erro ao classificar: ${error.message}`);
  } finally {
    busy = false;
  }
}

function handleScores(scores) {
  const top = Array.from(scores, (value, index) => ({ value, index }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 3);
  $("top3").replaceChildren(
    ...top.map((t) => {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = classNames[t.index] || `classe ${t.index}`;
      const pct = document.createElement("span");
      pct.textContent = `${Math.round(t.value * 100)}%`;
      li.append(name, pct);
      return li;
    })
  );

  const now = Date.now();
  for (const [eventId, def] of Object.entries(EVENTS)) {
    const score = Math.max(...def.classes.map((i) => scores[i]));
    hits[eventId] = score >= threshold() ? (hits[eventId] || 0) + 1 : 0;
    const cooledDown = !lastSent[eventId] || now - lastSent[eventId] >= COOLDOWN_MS;
    if (hits[eventId] >= CONFIRMATIONS && cooledDown) {
      lastSent[eventId] = now;
      hits[eventId] = 0;
      sendEvent(eventId, score);
    }
  }
}

async function sendEvent(eventId, confidence) {
  const label = EVENTS[eventId].label;
  const pct = `${Math.round(confidence * 100)}%`;
  $("last").textContent = label;
  $("last-detail").textContent = `${pct} · enviando evento ao Flask...`;
  let ok = false;
  let message = "";
  try {
    const response = await fetch("/api/sensor-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: crypto.randomUUID(),
        event: eventId,
        confidence: Math.round(confidence * 100) / 100,
        timestamp: new Date().toISOString(),
      }),
    });
    const result = await response.json();
    ok = response.ok && result.success === true;
    message = !ok
      ? result.message || `erro HTTP ${response.status}`
      : result.esp32_notified
        ? "salvo; ESP32 avisado"
        : "salvo no painel; ESP32 sem conexão";
  } catch (error) {
    message = "sem conexão com o Flask";
  }
  $("last-detail").textContent = `${pct} · ${message} · ${new Date().toLocaleTimeString("pt-BR")}`;
  const li = document.createElement("li");
  li.dataset.ok = String(ok);
  const left = document.createElement("span");
  left.textContent = `${ok ? "✓" : "✗"} ${label} (${pct})`;
  const right = document.createElement("span");
  right.textContent = message;
  li.append(left, right);
  $("log").prepend(li);
  while ($("log").children.length > 8) $("log").lastChild.remove();
}

// ---------- start / stop ----------
async function start() {
  toggleBtn.disabled = true;
  try {
    setStatus("loading", "Pedindo permissão do microfone...");
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });

    setStatus("loading", "Carregando o modelo de sons...");
    await Promise.all([ensureModel(), loadClassNames()]);

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await audioCtx.resume();
    const source = audioCtx.createMediaStreamSource(stream);
    const resampler = new Resampler(audioCtx.sampleRate, SAMPLE_RATE);

    // ScriptProcessor é antigo, mas funciona em todo celular e dispensa arquivo extra.
    processor = audioCtx.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (e) => {
      const chunk = e.inputBuffer.getChannelData(0);
      e.outputBuffer.getChannelData(0).fill(0);
      let sum = 0;
      for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
      levelEl.style.width = `${Math.min(100, Math.sqrt(sum / chunk.length) * 400)}%`;
      pushSamples(resampler.push(chunk));
      if (filled >= WINDOW && pending >= HOP && !busy) {
        pending = 0;
        classify();
      }
    };
    source.connect(processor);
    processor.connect(audioCtx.destination);

    if (navigator.wakeLock) {
      try { wakeLock = await navigator.wakeLock.request("screen"); } catch { /* opcional */ }
    }
    running = true;
    toggleBtn.dataset.on = "true";
    toggleBtn.textContent = "Parar monitoramento";
    setStatus("on", "Ouvindo");
  } catch (error) {
    const denied = error && error.name === "NotAllowedError";
    setStatus("error", denied ? "Permissão do microfone negada." : error.message);
    await stop(false);
  } finally {
    toggleBtn.disabled = false;
  }
}

async function stop(updateUi = true) {
  running = false;
  if (processor) { processor.disconnect(); processor.onaudioprocess = null; processor = null; }
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  if (audioCtx) { await audioCtx.close(); audioCtx = null; }
  if (wakeLock) { try { await wakeLock.release(); } catch { /* ok */ } wakeLock = null; }
  filled = 0; writeIdx = 0; pending = 0;
  levelEl.style.width = "0";
  if (updateUi) {
    toggleBtn.dataset.on = "false";
    toggleBtn.textContent = "Iniciar monitoramento";
    setStatus("idle", "Parado");
  }
}

toggleBtn.addEventListener("click", () => (running ? stop() : start()));

document.addEventListener("visibilitychange", async () => {
  if (running && document.visibilityState === "visible" && navigator.wakeLock && !wakeLock) {
    try { wakeLock = await navigator.wakeLock.request("screen"); } catch { /* opcional */ }
  }
});

if (!window.isSecureContext || !navigator.mediaDevices) {
  $("insecure").hidden = false;
  toggleBtn.disabled = true;
  setStatus("error", "Microfone indisponível nesta página (precisa de HTTPS)");
}

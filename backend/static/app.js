const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
const eventCount = document.querySelector("#event-count");
const eventList = document.querySelector("#event-list");
const emptyState = document.querySelector("#empty-state");
const feedback = document.querySelector("#feedback");
const refreshButton = document.querySelector("#refresh-button");
const simulatorForm = document.querySelector("#simulator-form");
const simulateButton = document.querySelector("#simulate-button");
const simulationFeedback = document.querySelector("#simulation-feedback");

let isRefreshing = false;

function setConnectionState(state, label) {
  connection.dataset.state = state;
  connectionLabel.textContent = label;
}

function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function createEventItem(event) {
  const item = document.createElement("li");
  item.className = "event-item";

  const symbol = document.createElement("span");
  symbol.className = "event-symbol";
  symbol.setAttribute("aria-hidden", "true");
  symbol.textContent = "♪";

  const details = document.createElement("div");
  const description = document.createElement("h3");
  description.className = "event-description";
  description.textContent = event.description || event.event;

  const meta = document.createElement("div");
  meta.className = "event-meta";

  const timestamp = document.createElement("time");
  timestamp.textContent = formatTimestamp(event.timestamp);
  const device = document.createElement("span");
  device.textContent = event.device;
  const eventType = document.createElement("span");
  eventType.textContent = event.event;

  meta.append(timestamp, device, eventType);
  details.append(description, meta);

  const confidence = document.createElement("span");
  confidence.className = "event-confidence";
  confidence.textContent = `${Math.round(event.confidence * 100)}%`;
  confidence.setAttribute("aria-label", `Confiança: ${confidence.textContent}`);

  item.append(symbol, details, confidence);
  return item;
}

function renderEvents(events) {
  const fragment = document.createDocumentFragment();
  for (const event of events) {
    fragment.append(createEventItem(event));
  }
  eventList.replaceChildren(fragment);

  const count = events.length;
  eventCount.textContent = count === 1 ? "1 evento registrado" : `${count} eventos registrados`;
  emptyState.hidden = count !== 0;
}

async function refreshEvents() {
  if (isRefreshing) {
    return;
  }

  isRefreshing = true;
  refreshButton.disabled = true;
  feedback.hidden = true;

  try {
    const [healthResponse, eventsResponse] = await Promise.all([
      fetch("/api/health", { cache: "no-store" }),
      fetch("/api/events", { cache: "no-store" }),
    ]);

    if (!healthResponse.ok || !eventsResponse.ok) {
      throw new Error("O servidor respondeu com erro.");
    }

    const [health, result] = await Promise.all([
      healthResponse.json(),
      eventsResponse.json(),
    ]);

    if (health.status !== "online" || !Array.isArray(result.events)) {
      throw new Error("O servidor retornou uma resposta inesperada.");
    }

    renderEvents(result.events);
    setConnectionState("online", "Sistema conectado");
  } catch {
    setConnectionState("offline", "Sem conexão com o sistema");
    eventCount.textContent = "Não foi possível atualizar os eventos.";
    feedback.textContent = "Verifique se o backend está em execução e tente novamente.";
    feedback.hidden = false;
  } finally {
    isRefreshing = false;
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", refreshEvents);
simulatorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  simulateButton.disabled = true;
  simulationFeedback.hidden = true;

  try {
    const response = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event: document.querySelector("#simulated-event").value,
      }),
    });
    const result = await response.json();

    if (!response.ok || result.success !== true) {
      throw new Error(result.message || "Não foi possível enviar o evento simulado.");
    }

    simulationFeedback.dataset.state = result.esp32_notified ? "success" : "warning";
    simulationFeedback.textContent = result.esp32_notified
      ? "Evento salvo. Observe os LEDs e aguarde até 5 segundos para vê-lo no histórico."
      : `${result.message} O evento já está no histórico.`;
    await refreshEvents();
  } catch (error) {
    simulationFeedback.dataset.state = "error";
    simulationFeedback.textContent = error.message;
  } finally {
    simulationFeedback.hidden = false;
    simulateButton.disabled = false;
  }
});

refreshEvents();
window.setInterval(refreshEvents, 5000);

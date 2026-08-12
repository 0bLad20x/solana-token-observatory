async function readJson(response, fallbackMessage) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    if (!response.ok) throw new Error(`${fallbackMessage}: ${response.status}`);
    throw new Error("Server returned invalid JSON");
  }
  if (!response.ok) throw new Error(payload.detail || `${fallbackMessage}: ${response.status}`);
  return payload;
}

export async function fetchTelemetry() {
  const response = await fetch("/api/telemetry");
  return readJson(response, "Telemetry request failed");
}

export async function requestAnalyst(body) {
  const response = await fetch("/api/analyst", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response, "Analyst request failed");
}

export function connectUniverseStream({ onOpen, onError, onSnapshot, onDelta }) {
  const stream = new EventSource("/api/events");
  stream.addEventListener("open", () => onOpen?.());
  stream.addEventListener("error", event => onError?.(event));
  stream.addEventListener("universe_snapshot", message => {
    try {
      const snapshot = JSON.parse(message.data);
      onSnapshot?.(snapshot);
    } catch (error) {
      console.warn("Invalid universe snapshot", error);
    }
  });
  stream.addEventListener("universe_delta", message => {
    try {
      const delta = JSON.parse(message.data);
      onDelta?.(delta);
    } catch (error) {
      console.warn("Invalid universe delta", error);
    }
  });
  return stream;
}

export function connectTelemetryStream({ onOpen, onError, onSnapshot, onEvent }) {
  const stream = new EventSource("/api/telemetry/events");
  stream.addEventListener("open", () => onOpen?.());
  stream.addEventListener("error", event => onError?.(event));
  stream.addEventListener("telemetry_snapshot", message => {
    try {
      onSnapshot?.(JSON.parse(message.data));
    } catch (error) {
      console.warn("Invalid telemetry snapshot", error);
    }
  });
  stream.addEventListener("telemetry_event", message => {
    try {
      onEvent?.(JSON.parse(message.data));
    } catch (error) {
      console.warn("Invalid telemetry event", error);
    }
  });
  return stream;
}

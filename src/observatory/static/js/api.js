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

export async function fetchUniverse() {
  const response = await fetch("/api/universe");
  return readJson(response, "Universe request failed");
}

export async function fetchToken(mint) {
  const response = await fetch(`/api/token/${encodeURIComponent(mint)}`);
  return readJson(response, "Token request failed");
}

export async function requestAnalyst(body) {
  const response = await fetch("/api/analyst", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson(response, "Analyst request failed");
}

export function connectUniverseStream({ onOpen, onError, onDelta }) {
  const stream = new EventSource("/api/events");
  stream.addEventListener("open", () => onOpen?.());
  stream.addEventListener("error", event => onError?.(event));
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

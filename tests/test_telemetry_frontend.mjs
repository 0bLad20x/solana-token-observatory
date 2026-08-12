import assert from "node:assert/strict";
import test from "node:test";

import { connectTelemetryStream } from "../src/observatory/static/js/api.js";

class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = new Map();
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, payload = {}) {
    this.listeners.get(name)?.(payload);
  }
}

test("telemetry stream uses its own snapshot and event contract", () => {
  const previous = globalThis.EventSource;
  globalThis.EventSource = FakeEventSource;

  try {
    const received = [];
    const stream = connectTelemetryStream({
      onSnapshot: payload => received.push(["snapshot", payload]),
      onEvent: payload => received.push(["event", payload]),
    });

    assert.equal(stream.url, "/api/telemetry/events");
    stream.emit("telemetry_snapshot", {
      data: JSON.stringify({ window_seconds: 600, events: [{ type: "search_flush" }] }),
    });
    stream.emit("telemetry_event", {
      data: JSON.stringify({ type: "search_lane_tick", lane: "lane0" }),
    });

    assert.deepEqual(received, [
      ["snapshot", { window_seconds: 600, events: [{ type: "search_flush" }] }],
      ["event", { type: "search_lane_tick", lane: "lane0" }],
    ]);
  } finally {
    globalThis.EventSource = previous;
  }
});

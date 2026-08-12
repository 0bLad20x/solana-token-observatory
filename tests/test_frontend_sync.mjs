import assert from "node:assert/strict";
import test from "node:test";

import { ActivityTracker } from "../src/observatory/static/js/activity.js";
import { connectUniverseStream } from "../src/observatory/static/js/api.js";
import { ObservatoryState } from "../src/observatory/static/js/state.js";

class FakeEventSource {
  static latest = null;

  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    FakeEventSource.latest = this;
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, payload = {}) {
    this.listeners.get(name)?.(payload);
  }
}

test("stream exposes synchronization snapshot separately from deltas", () => {
  const previous = globalThis.EventSource;
  globalThis.EventSource = FakeEventSource;

  try {
    const received = [];
    const stream = connectUniverseStream({
      onSnapshot: payload => received.push(["snapshot", payload]),
      onDelta: payload => received.push(["delta", payload]),
    });

    assert.equal(stream.url, "/api/events");
    stream.emit("universe_snapshot", {
      data: JSON.stringify({ generated_at: "2026-08-12T17:00:00Z", tokens: [{ mint: "A" }] }),
    });
    stream.emit("universe_delta", {
      data: JSON.stringify({ generated_at: "2026-08-12T17:00:02Z", events: [{ type: "token_added" }] }),
    });

    assert.deepEqual(received, [
      ["snapshot", { generated_at: "2026-08-12T17:00:00Z", tokens: [{ mint: "A" }] }],
      ["delta", { generated_at: "2026-08-12T17:00:02Z", events: [{ type: "token_added" }] }],
    ]);
  } finally {
    globalThis.EventSource = previous;
    FakeEventSource.latest = null;
  }
});

test("population state has no arbitrary detail upsert path", () => {
  const state = new ObservatoryState();
  assert.equal(typeof state.upsert, "undefined");

  state.load([{ mint: "A", tracking_enabled: true, market_cap: 1 }]);
  state.applyEvent({
    type: "token_updated",
    token: { mint: "A", tracking_enabled: true, market_cap: 2 },
  });

  assert.equal(state.token("A").market_cap, 2);
});

test("stream resync can clear incomplete derived activity", () => {
  const activity = new ActivityTracker();
  activity.applyEvent({
    type: "token_added",
    token: { mint: "A" },
  }, 1_000);
  assert.equal(activity.changedCount(1_000), 1);

  activity.reset();
  assert.equal(activity.changedCount(1_000), 0);
  assert.deepEqual(activity.topVolumeActivity(1_000), []);
});

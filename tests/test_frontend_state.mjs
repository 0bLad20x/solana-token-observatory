import assert from "node:assert/strict";
import test from "node:test";

import { ActivityTracker } from "../src/observatory/static/js/activity.js";
import { searchTokens } from "../src/observatory/static/js/search.js";
import { ObservatoryState } from "../src/observatory/static/js/state.js";

function token(
  mint,
  symbol,
  name,
  {
    trackingEnabled = true,
    marketCap = null,
    liquidity = null,
    holders = null,
    volume5m = null,
  } = {},
) {
  return {
    mint,
    symbol,
    name,
    launchpad: "pump.fun",
    tracking_enabled: trackingEnabled,
    market_cap: marketCap,
    liquidity,
    holders,
    volume_5m: volume5m,
  };
}

function volumeEvent(
  mint,
  { volumeBefore, volumeAfter, marketCapBefore, marketCapAfter },
) {
  return {
    type: "token_updated",
    token: token(mint, mint, mint, {
      marketCap: marketCapAfter,
      volume5m: volumeAfter,
    }),
    changes: {
      volume_5m: {
        absolute: volumeBefore == null || volumeAfter == null
          ? null
          : volumeAfter - volumeBefore,
      },
      market_cap: {
        absolute: marketCapBefore == null || marketCapAfter == null
          ? null
          : marketCapAfter - marketCapBefore,
      },
    },
  };
}

test("state owns population, selection, and event application only", () => {
  const state = new ObservatoryState();
  assert.equal("activeView" in state, false);
  assert.equal(typeof state.searchTokens, "undefined");
  assert.equal(typeof state.topVolumeActivity, "undefined");
  const first = token("MintA11111111111111111111111111111111111", "ONE", "One");
  state.load([first]);

  assert.equal(state.select(first.mint), true);
  assert.equal(state.selectedToken().symbol, "ONE");

  const updated = { ...first, market_cap: 100 };
  assert.equal(state.applyEvent({ type: "token_updated", token: updated }), true);
  assert.equal(state.selectedToken().market_cap, 100);

  state.applyEvent({ type: "token_retired", token: updated, reason: "test" });
  assert.equal(state.selectedToken().tracking_enabled, false);
  assert.equal(state.selectedToken().disabled_reason, "test");
});

test("search sorts matching identities by market cap", () => {
  const tokens = [
    token("ExactMint1111111111111111111111111111111", "CAT", "Cat Coin", { marketCap: 10 }),
    token("OtherMint2222222222222222222222222222222", "CATS", "Cats Club", { marketCap: 100 }),
    token("MissingMint33333333333333333333333333333", "CATX", "Cat Unknown"),
  ];

  assert.deepEqual(searchTokens(tokens, "cat").map(item => item.symbol), ["CATS", "CAT", "CATX"]);
  assert.equal(searchTokens(tokens, "ExactMint1111111111111111111111111111111")[0].symbol, "CAT");
});

test("search covers name and mint but excludes retired tokens", () => {
  const tokens = [
    token("AlphaMint1111111111111111111111111111111", "AAA", "Northern Light"),
    token("RetiredMint22222222222222222222222222222", "OLD", "Northern Ghost", {
      trackingEnabled: false,
    }),
  ];

  assert.deepEqual(searchTokens(tokens, "northern").map(item => item.symbol), ["AAA"]);
  assert.deepEqual(searchTokens(tokens, "alphamint").map(item => item.symbol), ["AAA"]);
});

test("search sees tokens added to live application state", () => {
  const state = new ObservatoryState();
  state.load([token("MintA11111111111111111111111111111111111", "ONE", "Shared One")]);
  state.applyEvent({
    type: "token_added",
    token: token("MintC33333333333333333333333333333333333", "NEW", "Fresh Arrival"),
  });

  assert.equal(searchTokens(state.values(), "fresh")[0].symbol, "NEW");
});

test("60 second change count is a separate derived signal and distinct by mint", () => {
  const activity = new ActivityTracker();
  const first = token("MintA11111111111111111111111111111111111", "ONE", "One");
  const second = token("MintB22222222222222222222222222222222222", "TWO", "Two");

  activity.applyEvent({ type: "token_added", token: first }, 1_000);
  activity.applyEvent({ type: "token_updated", token: first }, 2_000);
  activity.applyEvent({ type: "token_added", token: second }, 3_000);

  assert.equal(activity.changedCount(3_000), 2);
  assert.equal(activity.changedCount(62_001), 1);
});

test("volume activity aggregates each mint over the rolling window", () => {
  const activity = new ActivityTracker();
  const mint = "MintA11111111111111111111111111111111111";

  activity.applyEvent(volumeEvent(mint, {
    volumeBefore: 100,
    volumeAfter: 200,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  activity.applyEvent(volumeEvent(mint, {
    volumeBefore: 200,
    volumeAfter: 250,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 2_000);

  const [result] = activity.topVolumeActivity(2_000);
  assert.equal(result.mint, mint);
  assert.equal(result.volumeBefore, 100);
  assert.equal(result.volumeAfter, 250);
  assert.equal(result.volumeChange, 150);
  assert.equal(result.ratioBefore, 0.1);
  assert.equal(result.ratioAfter, 0.25);
  assert.equal(result.ratioChange, 0.15);
  assert.equal(result.timestamp, 2_000);
});

test("volume activity ranks five distinct positive ratio increases", () => {
  const activity = new ActivityTracker();
  for (let index = 1; index <= 6; index += 1) {
    activity.applyEvent(volumeEvent(`mint-${index}`, {
      volumeBefore: 0,
      volumeAfter: index * 10,
      marketCapBefore: 1_000,
      marketCapAfter: 1_000,
    }), index * 100);
  }

  assert.deepEqual(
    activity.topVolumeActivity(1_000).map(event => event.mint),
    ["mint-6", "mint-5", "mint-4", "mint-3", "mint-2"],
  );
});

test("volume activity excludes missing, falling, and non-rising ratios", () => {
  const activity = new ActivityTracker();
  activity.applyEvent(volumeEvent("falling", {
    volumeBefore: 200,
    volumeAfter: 100,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  activity.applyEvent(volumeEvent("flat-ratio", {
    volumeBefore: 100,
    volumeAfter: 300,
    marketCapBefore: 1_000,
    marketCapAfter: 3_000,
  }), 1_000);
  activity.applyEvent(volumeEvent("missing", {
    volumeBefore: null,
    volumeAfter: 300,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  activity.applyEvent(volumeEvent("valid", {
    volumeBefore: 100,
    volumeAfter: 200,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);

  assert.deepEqual(activity.topVolumeActivity(1_000).map(event => event.mint), ["valid"]);
  assert.deepEqual(activity.topVolumeActivity(61_001), []);
});

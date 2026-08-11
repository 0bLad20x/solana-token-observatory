import assert from "node:assert/strict";
import test from "node:test";

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

test("search sorts matching identities by market cap", () => {
  const state = new ObservatoryState();
  state.load([
    token("ExactMint1111111111111111111111111111111", "CAT", "Cat Coin", { marketCap: 10 }),
    token("OtherMint2222222222222222222222222222222", "CATS", "Cats Club", { marketCap: 100 }),
    token("MissingMint33333333333333333333333333333", "CATX", "Cat Unknown"),
  ]);

  assert.deepEqual(
    state.searchTokens("cat").map(item => item.symbol),
    ["CATS", "CAT", "CATX"],
  );
  assert.equal(state.searchTokens("ExactMint1111111111111111111111111111111")[0].symbol, "CAT");
});

test("search covers name and mint but excludes retired tokens", () => {
  const state = new ObservatoryState();
  state.load([
    token("AlphaMint1111111111111111111111111111111", "AAA", "Northern Light"),
    token("RetiredMint22222222222222222222222222222", "OLD", "Northern Ghost", {
      trackingEnabled: false,
    }),
  ]);

  assert.deepEqual(state.searchTokens("northern").map(item => item.symbol), ["AAA"]);
  assert.deepEqual(state.searchTokens("alphamint").map(item => item.symbol), ["AAA"]);
});

test("search respects its result bound and live state", () => {
  const state = new ObservatoryState();
  state.load([
    token("MintA11111111111111111111111111111111111", "ONE", "Shared One"),
    token("MintB22222222222222222222222222222222222", "TWO", "Shared Two"),
  ]);

  assert.equal(state.searchTokens("shared", 1).length, 1);
  state.applyEvent({
    type: "token_added",
    token: token("MintC33333333333333333333333333333333333", "NEW", "Fresh Arrival"),
  });
  assert.equal(state.searchTokens("fresh")[0].symbol, "NEW");
});

test("60 second change count is distinct by mint", () => {
  const state = new ObservatoryState();
  const first = token("MintA11111111111111111111111111111111111", "ONE", "One");
  const second = token("MintB22222222222222222222222222222222222", "TWO", "Two");

  state.applyEvent({ type: "token_added", token: first }, 1_000);
  state.applyEvent({ type: "token_updated", token: first }, 2_000);
  state.applyEvent({ type: "token_added", token: second }, 3_000);

  assert.equal(state.stats(3_000).changed, 2);
  assert.equal(state.stats(62_001).changed, 1);
});

test("volume activity aggregates each mint over the rolling window", () => {
  const state = new ObservatoryState();
  const mint = "MintA11111111111111111111111111111111111";

  state.applyEvent(volumeEvent(mint, {
    volumeBefore: 100,
    volumeAfter: 200,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  state.applyEvent(volumeEvent(mint, {
    volumeBefore: 200,
    volumeAfter: 250,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 2_000);

  const [activity] = state.topVolumeActivity(2_000);
  assert.equal(activity.mint, mint);
  assert.equal(activity.volumeBefore, 100);
  assert.equal(activity.volumeAfter, 250);
  assert.equal(activity.volumeChange, 150);
  assert.equal(activity.ratioBefore, 0.1);
  assert.equal(activity.ratioAfter, 0.25);
  assert.equal(activity.ratioChange, 0.15);
  assert.equal(activity.timestamp, 2_000);
});

test("volume activity ranks five distinct positive ratio increases", () => {
  const state = new ObservatoryState();
  for (let index = 1; index <= 6; index += 1) {
    state.applyEvent(volumeEvent(`mint-${index}`, {
      volumeBefore: 0,
      volumeAfter: index * 10,
      marketCapBefore: 1_000,
      marketCapAfter: 1_000,
    }), index * 100);
  }

  assert.deepEqual(
    state.topVolumeActivity(1_000).map(event => event.mint),
    ["mint-6", "mint-5", "mint-4", "mint-3", "mint-2"],
  );
});

test("volume activity excludes missing, falling, and non-rising ratios", () => {
  const state = new ObservatoryState();
  state.applyEvent(volumeEvent("falling", {
    volumeBefore: 200,
    volumeAfter: 100,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  state.applyEvent(volumeEvent("flat-ratio", {
    volumeBefore: 100,
    volumeAfter: 300,
    marketCapBefore: 1_000,
    marketCapAfter: 3_000,
  }), 1_000);
  state.applyEvent(volumeEvent("missing", {
    volumeBefore: null,
    volumeAfter: 300,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);
  state.applyEvent(volumeEvent("valid", {
    volumeBefore: 100,
    volumeAfter: 200,
    marketCapBefore: 1_000,
    marketCapAfter: 1_000,
  }), 1_000);

  assert.deepEqual(state.topVolumeActivity(1_000).map(event => event.mint), ["valid"]);
  assert.deepEqual(state.topVolumeActivity(61_001), []);
});

export const DEFAULT_VIEW_ID = "launchpad-cluster";

export const VIEW_PRESETS = Object.freeze({
  [DEFAULT_VIEW_ID]: Object.freeze({
    id: DEFAULT_VIEW_ID,
    type: "bubble",
    layout: "cluster",
    x: null,
    y: null,
    size: "market_cap",
    color: "launchpad",
    group: "launchpad",
  }),
});

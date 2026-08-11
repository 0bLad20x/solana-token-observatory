export const DEFAULT_VIEW_ID = "launchpad-overview-focus";

export const VIEW_PRESETS = Object.freeze({
  [DEFAULT_VIEW_ID]: Object.freeze({
    id: DEFAULT_VIEW_ID,
    type: "bubble",
    layout: "overview-focus",
    overview: Object.freeze({
      group: "launchpad",
      size: "token_count",
      color: "launchpad",
    }),
    focus: Object.freeze({
      rank: "market_cap",
      size: "market_cap",
      color: "launchpad",
    }),
  }),
});

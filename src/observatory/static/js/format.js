const numberCompact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
export const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
export const ratioFormat = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
export const timeFormat = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function money(value) {
  return value == null ? "—" : `$${numberCompact.format(value)}`;
}

export function count(value) {
  return value == null ? "—" : integerFormat.format(value);
}

export function duration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds < 18000 ? 1 : 0)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function tokenIdentity(token) {
  return token.symbol || token.name || token.mint.slice(0, 8);
}

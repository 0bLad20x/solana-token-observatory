export const COLORS = Object.freeze({
  background: 0x080b14,
  surface: 0x0f1420,
  surfaceRaised: 0x151b2a,
  border: 0x252c3d,
  textPrimary: 0xf3f5f8,
  textSecondary: 0x929bad,
  textMuted: 0x626c7e,
  solPurple: 0x9945ff,
  solCyan: 0x14f1d9,
  positive: 0x3ddc97,
  destructive: 0xff5c77,
  warning: 0xffb454,
  analyst: 0xb77cff,
  selection: 0x49d9ff,
  inactive: 0x5e6678,
});

const GROUP_PALETTE = Object.freeze([
  0x5b8cff,
  0xffb454,
  0xff7ac8,
  0x8b7cff,
  0x50c7a7,
  0xe48b5b,
]);

function paletteIndex(value) {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return (result >>> 0) % GROUP_PALETTE.length;
}

export function launchpadAccent(launchpad) {
  const value = String(launchpad || "unknown").toLowerCase();
  if (value.includes("pump")) return COLORS.solPurple;
  if (value.includes("meteora") || value.includes("dynamic bonding") || value === "met-dbc") return COLORS.solCyan;
  if (value.includes("jupiter") || value.includes("jup-studio")) return COLORS.positive;
  if (value.includes("raydium")) return COLORS.warning;
  if (value.includes("bags")) return 0xff7ac8;
  if (value.includes("bonk")) return 0xffb454;
  if (value === "unknown") return COLORS.inactive;
  return GROUP_PALETTE[paletteIndex(value)];
}

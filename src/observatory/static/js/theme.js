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

export function launchpadAccent(launchpad) {
  const value = String(launchpad || "unknown").toLowerCase();
  if (value.includes("pump")) return COLORS.solPurple;
  if (value.includes("meteora")) return COLORS.solCyan;
  if (value.includes("jupiter")) return COLORS.positive;
  return COLORS.inactive;
}

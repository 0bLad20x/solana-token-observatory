import { hierarchy, pack } from "https://cdn.jsdelivr.net/npm/d3-hierarchy@3.1.2/+esm";

export function visibleCapacity(width, height) {
  const usableArea = Math.max(1, width * height);
  return Math.max(80, Math.min(360, Math.floor(usableArea / 2200)));
}

export function equalSlots(ids, width, height, padding) {
  if (!ids.length) return [];

  const root = hierarchy({
    children: ids.map(id => ({ id, value: 1 })),
  })
    .sum(item => item.value || 0)
    .sort((a, b) => String(a.data.id || "").localeCompare(String(b.data.id || "")));

  pack()
    .size([Math.max(1, width), Math.max(1, height)])
    .padding(padding)(root);

  return root.leaves().map(leaf => ({
    id: leaf.data.id,
    x: leaf.x,
    y: leaf.y,
    radius: leaf.r,
  }));
}

export function percentile(values, ratio) {
  const sorted = values.filter(Number.isFinite).filter(value => value > 0).sort((a, b) => a - b);
  if (!sorted.length) return 1;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1));
  return sorted[index];
}

export function areaRadius(value, cap, slotRadius, minimum = 2.5) {
  const maximum = Math.max(minimum, slotRadius - 1.5);
  if (!Number.isFinite(value) || value <= 0) return minimum;
  return Math.max(minimum, maximum * Math.sqrt(Math.min(value, cap) / Math.max(1, cap)));
}

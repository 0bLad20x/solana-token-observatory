export function searchTokens(tokens, query, limit = 8) {
  const raw = String(query || "").trim();
  if (!raw || limit < 1) return [];
  const needle = raw.toLowerCase();

  const matches = [];
  for (const token of tokens) {
    if (!token.tracking_enabled) continue;
    const mint = String(token.mint || "");
    const symbol = String(token.symbol || "");
    const name = String(token.name || "");
    const values = [mint, symbol, name].map(value => value.toLowerCase());
    if (!values.some(value => value.includes(needle))) continue;

    matches.push({
      token,
      exactMint: mint === raw,
      marketCap: Number.isFinite(token.market_cap) ? token.market_cap : null,
      label: `${symbol}\u0000${name}\u0000${mint}`.toLowerCase(),
    });
  }

  return matches
    .sort((left, right) => {
      if (left.exactMint !== right.exactMint) return left.exactMint ? -1 : 1;
      if (left.marketCap !== right.marketCap) {
        if (left.marketCap == null) return 1;
        if (right.marketCap == null) return -1;
        return right.marketCap - left.marketCap;
      }
      return left.label.localeCompare(right.label);
    })
    .slice(0, limit)
    .map(match => match.token);
}

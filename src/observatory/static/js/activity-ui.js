import { money, ratioFormat, timeFormat, tokenIdentity } from "./format.js";

export class ActivityUI {
  constructor({ state, onSelect }) {
    this.state = state;
    this.onSelect = onSelect;
    this.feed = document.querySelector("#event-feed");
    this.rate = document.querySelector("#feed-rate");
  }

  render(activity) {
    this.rate.textContent = `${activity.length} ranked · 60s`;
    this.feed.replaceChildren();
    if (!activity.length) {
      const empty = document.createElement("li");
      empty.className = "event-empty";
      empty.textContent = "Waiting for positive 5m volume activity…";
      this.feed.append(empty);
      return;
    }

    for (const event of activity) {
      const token = this.state.token(event.mint);
      const item = document.createElement("li");
      item.className = "event-item";
      const choice = document.createElement("button");
      choice.type = "button";
      choice.className = "event-choice";
      choice.setAttribute("aria-label", `Select ${token ? tokenIdentity(token) : event.mint}`);
      choice.addEventListener("click", () => this.onSelect(event.mint));

      const meta = document.createElement("span");
      meta.className = "event-meta";
      const type = document.createElement("strong");
      type.className = "event-type";
      type.textContent = "VOLUME ↑";
      const time = document.createElement("time");
      time.dateTime = new Date(event.timestamp).toISOString();
      time.textContent = timeFormat.format(event.timestamp);
      meta.append(type, time);

      const copy = document.createElement("span");
      copy.className = "event-copy";
      const identity = document.createElement("strong");
      identity.textContent = token ? tokenIdentity(token) : event.mint.slice(0, 8);
      const volume = document.createElement("span");
      volume.textContent = `5m volume ${money(event.volumeBefore)} → ${money(event.volumeAfter)}`;
      const ratio = document.createElement("span");
      ratio.textContent = `Activity ${ratioFormat.format(event.ratioBefore)} → ${ratioFormat.format(event.ratioAfter)} · +${(event.ratioChange * 100).toFixed(1)} pp · MC ${money(event.marketCapAfter)}`;
      copy.append(identity, volume, ratio);
      choice.append(meta, copy);
      item.append(choice);
      this.feed.append(item);
    }
  }
}

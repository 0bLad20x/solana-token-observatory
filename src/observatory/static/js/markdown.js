function appendInline(parent, text) {
  const source = String(text || "");
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let cursor = 0;

  for (const match of source.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parent.append(document.createTextNode(source.slice(cursor, index)));

    const token = match[0];
    let element;
    if (token.startsWith("**")) {
      element = document.createElement("strong");
      element.textContent = token.slice(2, -2);
    } else if (token.startsWith("`")) {
      element = document.createElement("code");
      element.textContent = token.slice(1, -1);
    } else {
      element = document.createElement("em");
      element.textContent = token.slice(1, -1);
    }
    parent.append(element);
    cursor = index + token.length;
  }

  if (cursor < source.length) parent.append(document.createTextNode(source.slice(cursor)));
}

function tableCells(line) {
  let value = String(line || "").trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map(cell => cell.trim());
}

function isTableDivider(line) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}

function appendTable(container, lines, start) {
  const headers = tableCells(lines[start]);
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");

  for (const header of headers) {
    const cell = document.createElement("th");
    appendInline(cell, header);
    headRow.append(cell);
  }
  thead.append(headRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  let index = start + 2;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line || !line.includes("|")) break;
    const row = document.createElement("tr");
    for (const value of tableCells(line)) {
      const cell = document.createElement("td");
      appendInline(cell, value);
      row.append(cell);
    }
    tbody.append(row);
    index += 1;
  }
  table.append(tbody);

  const wrapper = document.createElement("div");
  wrapper.className = "markdown-table-wrap";
  wrapper.append(table);
  container.append(wrapper);
  return index;
}

export function renderMarkdown(container, text) {
  container.replaceChildren();
  const lines = String(text || "").split(/\r?\n/);
  let list = null;
  let listType = "";
  let index = 0;

  const resetList = () => {
    list = null;
    listType = "";
  };

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      resetList();
      index += 1;
      continue;
    }

    if (
      line.includes("|")
      && index + 1 < lines.length
      && isTableDivider(lines[index + 1])
    ) {
      resetList();
      index = appendTable(container, lines, index);
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
      container.append(document.createElement("hr"));
      resetList();
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length <= 2 ? "h3" : heading[1].length <= 4 ? "h4" : "h5";
      const element = document.createElement(level);
      appendInline(element, heading[2]);
      container.append(element);
      resetList();
      index += 1;
      continue;
    }

    const unordered = line.match(/^[-+*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const nextType = unordered ? "ul" : "ol";
      if (!list || listType !== nextType) {
        list = document.createElement(nextType);
        listType = nextType;
        container.append(list);
      }
      const item = document.createElement("li");
      appendInline(item, (unordered || ordered)[1]);
      list.append(item);
      index += 1;
      continue;
    }

    const paragraph = document.createElement("p");
    appendInline(paragraph, line);
    container.append(paragraph);
    resetList();
    index += 1;
  }
}

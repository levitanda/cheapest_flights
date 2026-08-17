/* Inline SVG charts. No library, deliberately.
 *
 * The whole page is four small static files; pulling in a charting bundle
 * would cost more than everything else combined and buy nothing these three
 * shapes need. Colours come from the same CSS variables as the rest of the
 * page, so light/dark and any future theming follow for free.
 *
 * RTL: the SVG itself is always drawn left-to-right and marked
 * direction:ltr. Mirroring the plot area under `dir=rtl` would flip the time
 * axis, and a price history that runs backwards is worse than one that runs
 * against the text.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/** SVG tooltip. `Element.append` returns undefined, so chaining .textContent
 *  onto it silently sets a property on nothing — hence a named helper. */
function tooltip(node, text) {
  const title = svgEl("title");
  title.textContent = text;
  node.appendChild(title);
  return node;
}

function chartFrame(width, height, title) {
  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    width: "100%",
    height,
    role: "img",
    style: "direction:ltr",
  });
  tooltip(svg, title);
  return svg;
}

/* ---------- price by departure month ---------- */

function monthChart(rows, { money, monthLabel, title, cheapestLabel }) {
  // rows: [{month: "2026-10", price: 137}, …] already sorted by month
  const W = 640, H = 220, PAD_L = 46, PAD_B = 34, PAD_T = 14, PAD_R = 8;
  const svg = chartFrame(W, H, title);
  if (!rows.length) return svg;

  const max = Math.max(...rows.map((r) => r.price));
  const min = Math.min(...rows.map((r) => r.price));
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const barW = Math.min(56, (plotW / rows.length) * 0.72);
  const step = plotW / rows.length;

  // Baseline and a mid gridline; two lines are enough to read a bar chart.
  [0, 0.5, 1].forEach((f) => {
    const y = PAD_T + plotH * f;
    svg.append(svgEl("line", {
      x1: PAD_L, x2: W - PAD_R, y1: y, y2: y,
      stroke: "var(--line)", "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: PAD_L - 6, y: y + 4, "text-anchor": "end",
      fill: "var(--muted)", "font-size": 11,
    });
    label.textContent = money(max * (1 - f));
    svg.append(label);
  });

  rows.forEach((row, i) => {
    const h = max > 0 ? (row.price / max) * plotH : 0;
    const x = PAD_L + i * step + (step - barW) / 2;
    const y = PAD_T + plotH - h;
    const cheapest = row.price === min;

    const bar = svgEl("rect", {
      x, y, width: barW, height: Math.max(h, 2), rx: 4,
      fill: cheapest ? "var(--good)" : "var(--accent)",
      opacity: cheapest ? 1 : 0.75,
    });
    tooltip(bar, `${monthLabel(row.month)}: ${money(row.price)}`);
    svg.append(bar);

    if (cheapest) {
      const tag = svgEl("text", {
        x: x + barW / 2, y: y - 4, "text-anchor": "middle",
        fill: "var(--good)", "font-size": 11, "font-weight": 600,
      });
      tag.textContent = money(row.price);
      svg.append(tag);
    }

    const label = svgEl("text", {
      x: x + barW / 2, y: H - 12, "text-anchor": "middle",
      fill: "var(--muted)", "font-size": 11,
    });
    label.textContent = monthLabel(row.month, true);
    svg.append(label);
  });

  if (cheapestLabel) {
    const best = rows.find((r) => r.price === min);
    const caption = svgEl("text", {
      x: PAD_L, y: 10, fill: "var(--muted)", "font-size": 11,
    });
    caption.textContent = cheapestLabel(monthLabel(best.month), money(min));
    svg.append(caption);
  }
  return svg;
}

/* ---------- price history ---------- */

function historyChart(series, { money, dateLabel, title }) {
  // series: {days: ["2026-08-12", …], prices: [111, …]}
  const W = 640, H = 200, PAD_L = 46, PAD_B = 28, PAD_T = 12, PAD_R = 8;
  const svg = chartFrame(W, H, title);
  const prices = series.prices || [];
  if (prices.length < 2) return svg;

  const max = Math.max(...prices), min = Math.min(...prices);
  const span = max - min || max || 1;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
  const x = (i) => PAD_L + (prices.length === 1 ? plotW / 2 : (i / (prices.length - 1)) * plotW);
  const y = (v) => PAD_T + plotH - ((v - min) / span) * plotH;

  [0, 0.5, 1].forEach((f) => {
    const gy = PAD_T + plotH * f;
    svg.append(svgEl("line", {
      x1: PAD_L, x2: W - PAD_R, y1: gy, y2: gy, stroke: "var(--line)", "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: PAD_L - 6, y: gy + 4, "text-anchor": "end", fill: "var(--muted)", "font-size": 11,
    });
    label.textContent = money(min + span * (1 - f));
    svg.append(label);
  });

  const points = prices.map((p, i) => `${x(i)},${y(p)}`).join(" ");
  svg.append(svgEl("polyline", {
    points, fill: "none", stroke: "var(--accent)",
    "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
  }));
  svg.append(svgEl("polygon", {
    points: `${PAD_L},${PAD_T + plotH} ${points} ${x(prices.length - 1)},${PAD_T + plotH}`,
    fill: "var(--accent)", opacity: 0.12,
  }));

  prices.forEach((p, i) => {
    const dot = svgEl("circle", {
      cx: x(i), cy: y(p), r: p === min ? 4 : 2.5,
      fill: p === min ? "var(--good)" : "var(--accent)",
    });
    tooltip(dot, `${dateLabel(series.days[i])}: ${money(p)}`);
    svg.append(dot);
  });

  [[series.days[0], PAD_L, "start"],
   [series.days[series.days.length - 1], W - PAD_R, "end"]].forEach(([day, px, anchor]) => {
    const label = svgEl("text", {
      x: px, y: H - 8, "text-anchor": anchor, fill: "var(--muted)", "font-size": 11,
    });
    label.textContent = dateLabel(day);
    svg.append(label);
  });
  return svg;
}

/* ---------- sparkline for a card ---------- */

function sparkline(prices, width = 76, height = 22) {
  const svg = chartFrame(width, height, "");
  if (!prices || prices.length < 2) return svg;
  const max = Math.max(...prices), min = Math.min(...prices);
  const span = max - min || 1;
  const points = prices.map((p, i) =>
    `${(i / (prices.length - 1)) * width},${height - ((p - min) / span) * (height - 4) - 2}`
  ).join(" ");
  svg.append(svgEl("polyline", {
    points, fill: "none", stroke: "var(--muted)", "stroke-width": 1.5,
  }));
  const last = prices[prices.length - 1];
  svg.append(svgEl("circle", {
    cx: width, cy: height - ((last - min) / span) * (height - 4) - 2, r: 2.5,
    fill: last <= min ? "var(--good)" : "var(--muted)",
  }));
  return svg;
}

/* ---------- destination × month heatmap ---------- */

function heatmap(destinations, months, cell, { money, monthLabel, nameOf, title }) {
  const ROW_H = 26, LABEL_W = 116, COL_W = 44, HEAD_H = 22;
  const W = LABEL_W + months.length * COL_W;
  const H = HEAD_H + destinations.length * ROW_H;
  const svg = chartFrame(W, H, title);

  const values = [];
  destinations.forEach((d) => months.forEach((m) => {
    const v = cell(d, m);
    if (v != null) values.push(v);
  }));
  if (!values.length) return svg;
  const lo = Math.min(...values), hi = Math.max(...values);

  months.forEach((m, i) => {
    const label = svgEl("text", {
      x: LABEL_W + i * COL_W + COL_W / 2, y: 14,
      "text-anchor": "middle", fill: "var(--muted)", "font-size": 10,
    });
    label.textContent = monthLabel(m, true);
    svg.append(label);
  });

  destinations.forEach((dest, r) => {
    const y = HEAD_H + r * ROW_H;
    const name = svgEl("text", {
      x: 0, y: y + 17, fill: "var(--ink)", "font-size": 12, style: "direction:inherit",
    });
    name.textContent = nameOf(dest);
    svg.append(name);

    months.forEach((m, c) => {
      const v = cell(dest, m);
      const x = LABEL_W + c * COL_W;
      if (v == null) {
        svg.append(svgEl("rect", {
          x: x + 1, y: y + 2, width: COL_W - 3, height: ROW_H - 5, rx: 3,
          fill: "var(--line)", opacity: 0.4,
        }));
        return;
      }
      // Green cheap → red dear, on a single hue ramp so the ordering reads
      // without a legend.
      const t = hi > lo ? (v - lo) / (hi - lo) : 0;
      const rect = svgEl("rect", {
        x: x + 1, y: y + 2, width: COL_W - 3, height: ROW_H - 5, rx: 3,
        fill: `hsl(${Math.round(140 - 140 * t)} 62% ${45 + 8 * (1 - t)}%)`,
      });
      tooltip(rect, `${nameOf(dest)} · ${monthLabel(m)}: ${money(v)}`);
      svg.append(rect);
    });
  });
  return svg;
}

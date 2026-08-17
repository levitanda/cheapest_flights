/* Rendering. Every string comes from i18n.js — nothing here is user-visible
 * text, which is what keeps adding a language cheap.
 *
 * Nodes are built with textContent rather than innerHTML: airline codes,
 * seller names and city names all originate outside our control.
 */

const DATA_URL = "data/deals.json";
const SYMBOL = { usd: "$", eur: "€", ils: "₪", gbp: "£", rub: "₽" };

const BUDGET_MAX = 1000;

let LANG = pickLang();
let T = I18N[LANG];
let PAYLOAD = null;

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const money = (v, cur) => {
  const n = new Intl.NumberFormat(T.locale, { maximumFractionDigits: 0 }).format(v);
  return SYMBOL[cur] ? SYMBOL[cur] + n : n + " " + (cur || "").toUpperCase();
};

const shortDate = (iso) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return new Intl.DateTimeFormat(T.locale, { day: "numeric", month: "short" }).format(d);
};

const dateRange = (from, to) => {
  const a = shortDate(from), b = shortDate(to);
  if (a && b) return a + " — " + b;
  if (a) return a + ", " + T.oneWay;
  return T.datesTbd;
};

const ago = (iso) => {
  const mins = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (!isFinite(mins) || mins < 0) return "";
  const rtf = new Intl.RelativeTimeFormat(T.locale, { numeric: "auto" });
  if (mins < 60) return rtf.format(-mins, "minute");
  if (mins < 1440) return rtf.format(-Math.floor(mins / 60), "hour");
  return rtf.format(-Math.floor(mins / 1440), "day");
};

const nameOf = (item) => (item.names && (item.names[LANG] || item.names.en)) || item.destination;

const tierLabel = (tier) => ({
  good: T.tierGood, great: T.tierGreat,
  exceptional: T.tierExceptional, error_fare: T.tierErrorFare,
}[tier] || tier);

/* ---------- shared pieces ---------- */

function buyRow(item, exact) {
  const row = el("div", "buy-row");
  if (item.url) {
    const a = el("a", "btn-buy", exact ? T.buyExact : T.buy);
    a.href = item.url;
    a.target = "_blank";
    a.rel = "noopener nofollow";
    row.append(a);
  }
  // Saying which of the two it is matters: quoting a price and linking to a
  // search that may not contain it is the complaint this project exists to
  // avoid making.
  row.append(el("span", "link-note", exact ? T.exactNote : T.searchNote));

  if (item.compare && item.compare.length) {
    const cmp = el("div", "compare");
    cmp.append(el("span", "label", T.compare));
    item.compare.forEach((c) => {
      const a = el("a", null, COMPARE_LABELS[c.id] || c.id);
      a.href = c.url;
      a.target = "_blank";
      a.rel = "noopener nofollow";
      cmp.append(a);
    });
    row.append(cmp);
  }
  return row;
}

function detailTags(item) {
  const tags = el("div", "tags");
  if (item.transfers === 0) tags.append(el("span", "tag", T.direct));
  else if (item.transfers > 0) tags.append(el("span", "tag", T.stops + " " + item.transfers));
  if (item.airline) tags.append(el("span", "tag", item.airline));
  if (item.seller) tags.append(el("span", "tag", T.seller + " " + item.seller));
  return tags;
}

/* ---------- deals ---------- */

function dealNode(d) {
  const node = el("div", "deal " + (d.tier || ""));

  const head = el("div", "deal-head");
  const left = el("div");
  const route = el("div", "route");
  route.append(
    document.createTextNode(nameOf(d) + " "),
    el("span", "code", "(" + d.origin + " → " + d.destination + ")")
  );
  left.append(route, el("div", "when", dateRange(d.depart_date, d.return_date)));

  const right = el("div", "price-block");
  right.append(el("div", "price-now tnum", money(d.price, d.currency)));
  if (d.baseline > d.price) {
    right.append(el("div", "price-was", money(d.baseline, d.currency)));
    right.append(el("div", "price-off", "−" + Math.round(d.drop_pct * 100) + "%"));
  }
  right.append(el("div", "per-person", T.perPerson));
  head.append(left, right);
  node.append(head);

  const tags = detailTags(d);
  if (d.trip_nights != null) tags.prepend(el("span", "tag", d.trip_nights + " " + T.nights));
  if (d.basis === "heuristic") tags.append(el("span", "tag", T.noHistoryBasis));
  if (d.tier) tags.prepend(el("span", "tag tier " + d.tier, tierLabel(d.tier)));
  node.append(tags);

  if (d.tier === "error_fare") node.append(el("div", "warn", T.errorFareWarning));
  node.append(buyRow(d, true));
  return node;
}

/* ---------- current fares ---------- */

function fareNode(f) {
  const node = el("div", "fare");
  const top = el("div", "top");
  top.append(el("span", "city", nameOf(f)), el("span", "amount tnum", money(f.price, f.currency)));
  node.append(top);
  node.append(el("div", "sub", dateRange(f.depart_date, f.return_date)));

  const bits = [f.origin + " → " + f.destination];
  if (f.transfers === 0) bits.push(T.direct);
  else if (f.transfers > 0) bits.push(T.stops + " " + f.transfers);
  if (f.airline) bits.push(f.airline);
  node.append(el("div", "sub", bits.join(" · ")));
  if (f.seller) node.append(el("div", "sub", T.seller + " " + f.seller));

  const series = (PAYLOAD.history || {})[`${f.origin}-${f.destination}`];
  if (series && (series.prices || []).length >= 3) {
    const spark = sparkline(series.prices);
    spark.classList.add("spark");
    top.querySelector(".amount").prepend(spark);
  }

  node.append(buyRow(f, Boolean(f.exact)));
  return node;
}

/* ---------- filtering ---------- */

function monthName(month, short) {
  const d = new Date(month + "-01T00:00:00Z");
  return new Intl.DateTimeFormat(T.locale, {
    month: short ? "short" : "long", year: short ? undefined : "numeric",
    timeZone: "UTC",
  }).format(d);
}

function countryName(code) {
  if (!code) return code;
  try {
    return new Intl.DisplayNames([T.locale], { type: "region" }).of(code) || code;
  } catch {
    return code;   // older engines, or a code Intl does not know
  }
}

function filters() {
  return {
    tokens: currentTokens(),
    country: document.getElementById("country").value,
    directOnly: document.getElementById("direct").checked,
    from: document.getElementById("from").value,
    to: document.getElementById("to").value,
    budget: Number(document.getElementById("budget").value),
  };
}

function withinDates(item, from, to) {
  // Both legs must sit inside the window. A fare that departs inside it and
  // returns three weeks later is not a trip you can take on those dates.
  if (from && (!item.depart_date || item.depart_date < from)) return false;
  if (to) {
    const back = item.return_date || item.depart_date;
    if (!back || back > to) return false;
  }
  return true;
}

function matches(item, f) {
  if (f.directOnly && item.transfers !== 0) return false;
  if (f.country && item.country !== f.country) return false;
  if (f.budget < BUDGET_MAX && item.price > f.budget) return false;
  if (!withinDates(item, f.from, f.to)) return false;
  if (!f.tokens.length) return true;
  const hay = [
    item.destination, item.origin, item.country, countryName(item.country),
    ...Object.values(item.names || {}),
    ...Object.values(item.origin_names || {}),
  ].filter(Boolean).join(" ").toLowerCase();
  return f.tokens.every((t) => hay.includes(t));
}

function currentTokens() {
  // Tokenised so picking a suggestion verbatim ("אתונה (ATH)") still matches.
  return document.getElementById("q").value.trim().toLowerCase()
    .split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

function apply() {
  if (!PAYLOAD) return;
  const f = filters();
  const tokens = f.tokens;
  const tier = document.getElementById("tier").value;
  const sort = document.getElementById("sort").value;

  let deals = (PAYLOAD.deals || []).filter(
    (d) => (!tier || d.tier === tier) && matches(d, f)
  );
  if (sort === "discount") deals.sort((a, b) => b.drop_pct - a.drop_pct);
  else if (sort === "price") deals.sort((a, b) => a.price - b.price);
  else deals.sort((a, b) => String(b.sent_at).localeCompare(String(a.sent_at)));

  const dealBox = document.getElementById("deals");
  if (!deals.length) {
    dealBox.replaceChildren(
      el("div", "empty", (PAYLOAD.deals || []).length ? T.nothingMatches : T.dealsEmpty)
    );
  } else {
    dealBox.replaceChildren(...deals.map(dealNode));
  }

  // With dates or a budget set, the month-level fares are the useful pool:
  // "cheapest right now" holds one date per route and would filter to nothing.
  const narrowed = Boolean(f.from || f.to || f.budget < BUDGET_MAX);
  const pool = narrowed ? (PAYLOAD.fares || []) : (PAYLOAD.current || []);
  let current = pool.filter((item) => matches(item, f));

  if (narrowed) current = cheapestPerDestination(current);
  current.sort((a, b) => a.price - b.price);

  const fareBox = document.getElementById("current");
  if (current.length) {
    fareBox.replaceChildren(...current.map(fareNode));
  } else if (!(PAYLOAD.current || []).length) {
    fareBox.replaceChildren(el("div", "empty", T.noPricesYet));
  } else if (narrowed) {
    fareBox.replaceChildren(el("div", "empty", T.noDataForFilter));
  } else {
    const place = resolveQueryPlace(tokens);
    fareBox.replaceChildren(place ? unpricedNode(place) : el("div", "empty", T.nothingMatches));
  }

  renderFocus(tokens, f);
}

function cheapestPerDestination(items) {
  const best = new Map();
  items.forEach((item) => {
    const seen = best.get(item.destination);
    if (!seen || item.price < seen.price) best.set(item.destination, item);
  });
  return [...best.values()];
}

/* ---------- charts ---------- */

const chartOpts = () => ({
  money: (v) => money(v, PAYLOAD.currency || "usd"),
  monthLabel: monthName,
  dateLabel: (iso) => shortDate(iso) || iso,
  nameOf: (code) => {
    const names = (PAYLOAD.places || {})[code];
    return (names && (names[LANG] || names.en)) || code;
  },
});

/** Which destination the charts should describe: an explicit country pick, a
 *  search that resolves to one place, or nothing. */
function focusTarget(tokens, f) {
  if (f.country) return { kind: "country", code: f.country, label: countryName(f.country) };
  const place = tokens.length ? resolveQueryPlace(tokens) : null;
  if (place && (PAYLOAD.fares || []).some((x) => x.destination === place.code)) {
    return { kind: "place", code: place.code, label: placeLabel(place.code, place.names) };
  }
  return null;
}

function renderFocus(tokens, f) {
  const section = document.getElementById("focus");
  const target = focusTarget(tokens, f);
  if (!target) { section.hidden = true; return; }

  const relevant = (PAYLOAD.fares || []).filter((x) =>
    target.kind === "country" ? x.country === target.code : x.destination === target.code);
  if (!relevant.length) { section.hidden = true; return; }

  section.hidden = false;
  document.getElementById("focus-head").textContent =
    T.focusHeading.replace("{place}", target.label);

  // Cheapest per month across whatever the target covers.
  const byMonth = new Map();
  relevant.forEach((x) => {
    const seen = byMonth.get(x.month);
    if (seen == null || x.price < seen) byMonth.set(x.month, x.price);
  });
  const rows = [...byMonth.entries()].sort().map(([month, price]) => ({ month, price }));

  const opts = chartOpts();
  document.getElementById("month-chart").replaceChildren(
    monthChart(rows, {
      ...opts,
      title: T.monthChartTitle,
      cheapestLabel: (month, price) =>
        T.cheapestMonth.replace("{month}", month).replace("{price}", price),
    })
  );

  document.getElementById("history-head").textContent = T.historyHeading;
  const series = target.kind === "place"
    ? (PAYLOAD.history || {})[`${relevant[0].origin}-${target.code}`]
    : null;
  const box = document.getElementById("history-chart");
  const note = document.getElementById("history-note");

  if (series && (series.prices || []).length >= 2) {
    box.replaceChildren(historyChart(series, { ...opts, title: T.historyHeading }));
    note.textContent = "";
  } else {
    // Better an honest sentence than a line drawn through two points.
    box.replaceChildren();
    const since = series ? series.days[0] : (PAYLOAD.stats || {}).first_seen;
    note.textContent = T.historyTooShort.replace(
      "{date}", since ? (shortDate(since) || since.slice(0, 10)) : "—");
  }
}

function renderHeatmap() {
  document.getElementById("heatmap-head").textContent = T.heatmapHeading;
  document.getElementById("heatmap-hint").textContent = T.heatmapHint;

  const fares = PAYLOAD.fares || [];
  if (!fares.length) return;

  const months = [...new Set(fares.map((x) => x.month))].sort().slice(0, 12);
  const cheapest = new Map();
  fares.forEach((x) => {
    const seen = cheapest.get(x.destination);
    if (seen == null || x.price < seen) cheapest.set(x.destination, x.price);
  });
  const destinations = [...cheapest.entries()]
    .sort((a, b) => a[1] - b[1]).slice(0, 15).map(([code]) => code);

  const lookup = new Map();
  fares.forEach((x) => {
    const key = x.destination + "|" + x.month;
    const seen = lookup.get(key);
    if (seen == null || x.price < seen) lookup.set(key, x.price);
  });

  document.getElementById("heatmap").replaceChildren(
    heatmap(destinations, months,
      (dest, month) => lookup.get(dest + "|" + month) ?? null,
      { ...chartOpts(), title: T.heatmapHeading })
  );
}

function fillCountries() {
  const select = document.getElementById("country");
  const codes = [...new Set(
    [...(PAYLOAD.current || []), ...(PAYLOAD.fares || [])]
      .map((x) => x.country).filter(Boolean)
  )];
  const options = codes
    .map((code) => ({ code, label: countryName(code) }))
    .sort((a, b) => a.label.localeCompare(b.label, T.locale));

  const previous = select.value;
  select.replaceChildren(
    new Option(T.allCountries, ""),
    ...options.map((o) => new Option(o.label, o.code))
  );
  select.value = previous;
}

/* ---------- static sections ---------- */

function renderStats() {
  const s = PAYLOAD.stats || {};
  const fmt = (n) => new Intl.NumberFormat(T.locale).format(n || 0);
  const items = [
    [fmt(s.alerts), T.findings],
    [fmt((PAYLOAD.current || []).length), T.destinations],
    [fmt(s.routes), T.routesTracked],
    [fmt(s.observations), T.observations],
  ];
  document.getElementById("stats").replaceChildren(
    ...items.map(([v, label]) => {
      const d = el("div", "stat");
      d.append(el("b", null, String(v)), el("span", null, label));
      return d;
    })
  );
}

function renderRoutes() {
  const rows = PAYLOAD.routes || [];
  const tbody = document.querySelector("#routes tbody");
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", null, T.routesEmpty);
    td.colSpan = 5;
    tr.append(td);
    tbody.replaceChildren(tr);
    return;
  }
  const head = el("tr");
  [[T.colDestination, 0], [T.colType, 0], [T.colObservations, 1],
   [T.colCheapest, 1], [T.colAverage, 1]].forEach(([label, num]) =>
    head.append(el("th", num ? "num" : null, label)));

  tbody.replaceChildren(head, ...rows.map((r) => {
    const tr = el("tr");
    tr.append(
      el("td", null, (r.names && (r.names[LANG] || r.names.en) || r.destination)
        + " (" + r.origin + "→" + r.destination + ")"),
      el("td", null, r.trip_kind === "ow" ? T.oneWay : T.roundTrip),
      el("td", "num", new Intl.NumberFormat(T.locale).format(r.observations)),
      el("td", "num", money(r.cheapest, r.currency)),
      el("td", "num", money(r.average, r.currency))
    );
    return tr;
  }));
}

function placeLabel(code, names) {
  const label = names && (names[LANG] || names.en);
  return label && label !== code ? label + " (" + code + ")" : code;
}

function fillSuggestions() {
  // Suggest every destination we know of, not only those currently priced —
  // otherwise typing a real city returns a blank page and reads as a broken
  // search rather than as missing data.
  const seen = new Map();
  Object.entries(PAYLOAD.places || {}).forEach(([code, names]) =>
    seen.set(code, placeLabel(code, names)));
  ["deals", "current", "routes"].forEach((key) =>
    (PAYLOAD[key] || []).forEach((item) => {
      if (!seen.has(item.destination)) seen.set(item.destination, placeLabel(item.destination, item.names));
      if (!seen.has(item.origin)) seen.set(item.origin, placeLabel(item.origin, item.origin_names));
    }));

  document.getElementById("places").replaceChildren(
    ...[...seen.values()].sort((a, b) => a.localeCompare(b, T.locale)).map((label) => {
      const o = document.createElement("option");
      o.value = label;
      return o;
    })
  );
}

/* When the query names a place we know but have no fare for, offer to search
 * it directly rather than showing an empty page. The long tail can never be
 * fully scanned, so this is the permanent answer for it, not a stopgap. */
function resolveQueryPlace(tokens) {
  if (!tokens.length) return null;
  const places = PAYLOAD.places || {};
  for (const [code, names] of Object.entries(places)) {
    const hay = [code, ...Object.values(names || {})].join(" ").toLowerCase();
    if (tokens.every((t) => hay.includes(t))) return { code, names };
  }
  return null;
}

function unpricedNode(place) {
  const origin = (PAYLOAD.current || [])[0]?.origin || "TLV";
  const box = el("div", "empty");
  box.append(el("div", null, T.noPriceFor.replace("{place}", placeLabel(place.code, place.names))));

  const links = el("div", "compare");
  links.style.justifyContent = "center";
  links.style.marginTop = "10px";
  const searches = [
    ["Aviasales", "https://www.aviasales.com/search/" + origin + place.code + "1"],
    ["Skyscanner", "https://www.skyscanner.co.il/transport/flights/"
      + origin.toLowerCase() + "/" + place.code.toLowerCase()
      + "/?adults=1&currency=USD&locale=he-IL&market=IL"],
    ["Google Flights", "https://www.google.com/travel/flights?q="
      + encodeURIComponent("Flights from " + origin + " to " + place.code)
      + "&hl=iw&gl=IL"],
  ];
  links.append(el("span", "label", T.searchItOn));
  searches.forEach(([label, href]) => {
    const a = el("a", null, label);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener nofollow";
    links.append(a);
  });
  box.append(links);
  return box;
}

function applyLanguage() {
  T = I18N[LANG];
  document.documentElement.lang = LANG;
  document.documentElement.dir = T.dir;
  document.title = T.title;
  document.querySelector('meta[name="description"]').content = T.description;

  const set = (id, value) => { document.getElementById(id).textContent = value; };
  set("h1", "✈️ " + T.title);
  set("tagline", T.tagline);
  set("current-head", T.currentHeading);
  set("current-hint", T.currentHint);
  set("routes-head", T.routesHeading);
  set("footer-text", T.footer);
  document.getElementById("source-link").textContent = T.sourceCode;

  const q = document.getElementById("q");
  q.placeholder = T.searchPlaceholder;
  document.getElementById("direct-label").textContent = T.directOnly;
  document.getElementById("from-label").textContent = T.dateFrom;
  document.getElementById("to-label").textContent = T.dateTo;
  document.getElementById("budget-label").textContent = T.budget;
  document.getElementById("reset").textContent = T.reset;
  updateBudgetLabel();

  const tier = document.getElementById("tier");
  const tierValue = tier.value;
  tier.replaceChildren(...[
    ["", T.allTiers], ["error_fare", T.tierErrorFare], ["exceptional", T.tierExceptional],
    ["great", T.tierGreat], ["good", T.tierGood],
  ].map(([value, label]) => new Option(label, value)));
  tier.value = tierValue;

  const sort = document.getElementById("sort");
  // On the first pass the select is empty, so reading its value yields "" —
  // which matches no option and would render the control blank.
  const sortValue = sort.value || "recent";
  sort.replaceChildren(...[
    ["recent", T.sortRecent], ["discount", T.sortDiscount], ["price", T.sortPrice],
  ].map(([value, label]) => new Option(label, value)));
  sort.value = sortValue;

  document.querySelectorAll(".langs button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));

  if (PAYLOAD) {
    document.getElementById("meta").textContent =
      T.updated + " " + ago(PAYLOAD.generated_at);
    renderStats();
    renderRoutes();
    fillSuggestions();
    fillCountries();
    renderHeatmap();
    apply();
  }
}

function switchTo(lang) {
  if (!I18N[lang] || lang === LANG) return;
  LANG = lang;
  try { localStorage.setItem("lang", lang); } catch { /* private mode */ }
  const url = new URL(location.href);
  url.searchParams.set("lang", lang);
  history.replaceState(null, "", url);
  applyLanguage();
}

function updateBudgetLabel() {
  const value = Number(document.getElementById("budget").value);
  document.getElementById("budget-value").textContent =
    value >= BUDGET_MAX ? T.anyBudget : money(value, (PAYLOAD && PAYLOAD.currency) || "usd");
}

/* ---------- boot ---------- */

function boot() {
  document.querySelectorAll(".langs button").forEach((b) => {
    b.textContent = I18N[b.dataset.lang].label;
    b.addEventListener("click", () => switchTo(b.dataset.lang));
  });
  ["q", "tier", "sort", "direct", "country", "from", "to", "budget"].forEach((id) =>
    document.getElementById(id).addEventListener("input", () => {
      updateBudgetLabel();
      apply();
    }));

  document.getElementById("reset").addEventListener("click", () => {
    ["q", "from", "to"].forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("country").value = "";
    document.getElementById("tier").value = "";
    document.getElementById("direct").checked = false;
    document.getElementById("budget").value = String(BUDGET_MAX);
    updateBudgetLabel();
    apply();
  });

  applyLanguage();

  fetch(DATA_URL, { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((p) => { PAYLOAD = p; applyLanguage(); })
    .catch((e) => {
      document.getElementById("meta").textContent = "";
      document.getElementById("deals").replaceChildren(
        el("div", "error", T.loadError + " (" + e.message + ")"));
    });
}

document.addEventListener("DOMContentLoaded", boot);

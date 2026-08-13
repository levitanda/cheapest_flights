/* Rendering. Every string comes from i18n.js — nothing here is user-visible
 * text, which is what keeps adding a language cheap.
 *
 * Nodes are built with textContent rather than innerHTML: airline codes,
 * seller names and city names all originate outside our control.
 */

const DATA_URL = "data/deals.json";
const SYMBOL = { usd: "$", eur: "€", ils: "₪", gbp: "£", rub: "₽" };

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

  node.append(buyRow(f, Boolean(f.exact)));
  return node;
}

/* ---------- filtering ---------- */

function matches(item, tokens, directOnly) {
  if (directOnly && item.transfers !== 0) return false;
  if (!tokens.length) return true;
  const hay = [
    item.destination, item.origin, item.country,
    ...Object.values(item.names || {}),
    ...Object.values(item.origin_names || {}),
  ].filter(Boolean).join(" ").toLowerCase();
  return tokens.every((t) => hay.includes(t));
}

function currentTokens() {
  // Tokenised so picking a suggestion verbatim ("אתונה (ATH)") still matches.
  return document.getElementById("q").value.trim().toLowerCase()
    .split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

function apply() {
  if (!PAYLOAD) return;
  const tokens = currentTokens();
  const tier = document.getElementById("tier").value;
  const sort = document.getElementById("sort").value;
  const directOnly = document.getElementById("direct").checked;

  let deals = (PAYLOAD.deals || []).filter(
    (d) => (!tier || d.tier === tier) && matches(d, tokens, directOnly)
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

  let current = (PAYLOAD.current || []).filter((f) => matches(f, tokens, directOnly));
  if (sort === "price" || sort === "recent") current.sort((a, b) => a.price - b.price);

  const fareBox = document.getElementById("current");
  if (current.length) {
    fareBox.replaceChildren(...current.map(fareNode));
  } else if (!(PAYLOAD.current || []).length) {
    fareBox.replaceChildren(el("div", "empty", T.noPricesYet));
  } else {
    const place = resolveQueryPlace(tokens);
    fareBox.replaceChildren(place ? unpricedNode(place) : el("div", "empty", T.nothingMatches));
  }
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

/* ---------- boot ---------- */

function boot() {
  document.querySelectorAll(".langs button").forEach((b) => {
    b.textContent = I18N[b.dataset.lang].label;
    b.addEventListener("click", () => switchTo(b.dataset.lang));
  });
  ["q", "tier", "sort", "direct"].forEach((id) =>
    document.getElementById(id).addEventListener("input", apply));

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

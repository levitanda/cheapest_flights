/* All user-visible text, in one place.
 *
 * Hebrew leads because the audience is Israeli; Russian is here because
 * roughly a million Israelis read it, and English for everyone else. Nothing
 * outside this file may contain a display string — that rule is what keeps a
 * third language from being a rewrite.
 */

const I18N = {
  he: {
    dir: "rtl",
    locale: "he-IL",
    label: "עברית",
    title: "טיסות זולות מישראל",
    tagline: "מחירים חריגים בטיסות מתל אביב, נמצאים אוטומטית מסביב לשעון.",
    description:
      "מעקב אחרי מחירי טיסות מישראל: מחירים נמוכים בצורה חריגה וטעויות תמחור, עם קישור ישיר לרכישה.",

    updated: "עודכן",
    findings: "מציאות",
    destinations: "יעדים עם מחיר",
    routesTracked: "מסלולים במעקב",
    observations: "בדיקות מחיר",

    searchPlaceholder: "חיפוש לפי עיר או קוד שדה תעופה…",
    allTiers: "כל הרמות",
    sortRecent: "החדשות ראשונות",
    sortDiscount: "לפי גודל ההנחה",
    sortPrice: "לפי מחיר",
    directOnly: "ללא עצירות בלבד",

    tierGood: "מחיר טוב",
    tierGreat: "מחיר מצוין",
    tierExceptional: "מחיר יוצא דופן",
    tierErrorFare: "כנראה טעות תמחור",

    dealsEmpty:
      "עדיין אין מחירים חריגים. המערכת צריכה היסטוריה של כמה ימים כדי להבדיל בין הנחה למחיר רגיל — בינתיים ראו את המחירים הזולים ביותר כרגע.",
    nothingMatches: "לא נמצא דבר בסינון הזה.",
    noPricesYet: "המערכת עדיין לא אספה מחירים.",
    noPriceFor: "עדיין לא נאסף מחיר ל־{place}. אפשר לחפש ישירות:",
    searchItOn: "חיפוש ב־",
    dateFrom: "מתאריך",
    dateTo: "עד תאריך",
    budget: "עד",
    anyBudget: "כל מחיר",
    reset: "איפוס",
    allCountries: "כל המדינות",
    focusHeading: "{place}: מחירים לאורך זמן",
    monthChartTitle: "מחיר לפי חודש יציאה",
    cheapestMonth: "הכי זול ב{month} — {price}",
    historyHeading: "איך המחיר השתנה",
    historyTooShort: "אוספים היסטוריה מאז {date}. הגרף יהיה משמעותי אחרי שבוע-שבועיים.",
    heatmapHeading: "לאן ומתי זול",
    heatmapHint: "כל תא הוא המחיר הזול ביותר ליעד בחודש הזה. ירוק = זול.",
    noDataForFilter: "אין טיסות בתאריכים האלה.",

    currentHeading: "הזול ביותר כרגע",
    currentHint:
      "המחיר הנמוך ביותר שנמצא לכל יעד בשלושת הימים האחרונים. לא בהכרח הנחה — פשוט הזול ביותר עכשיו.",
    routesHeading: "מסלולים במעקב",
    routesEmpty: "עדיין אין מסלולים שנאספו.",

    buy: "לרכישה",
    buyExact: "למחיר הזה",
    compare: "להשוואה:",
    seller: "נמכר ב־",
    exactNote: "הקישור מוביל בדיוק למחיר הזה",
    searchNote: "הקישור מוביל לחיפוש — המחיר עשוי להשתנות",

    nights: "לילות",
    direct: "ללא עצירות",
    stops: "עצירות:",
    oneWay: "לכיוון אחד",
    datesTbd: "תאריכים בהמשך",
    perPerson: "לאדם, הלוך ושוב",
    noHistoryBasis: "הערכה ללא היסטוריה",

    colDestination: "יעד",
    colType: "סוג",
    colObservations: "בדיקות",
    colCheapest: "מינימום",
    colAverage: "ממוצע",
    roundTrip: "הלוך ושוב",

    errorFareWarning:
      "טעויות תמחור נעלמות תוך שעות. הזמינו מיד, ואל תזמינו מלון עד לאישור מחברת התעופה.",
    loadError: "לא הצלחנו לטעון את הנתונים",
    loading: "טוען…",
    footer:
      "המחירים נאספים אוטומטית מ־Aviasales, שמשווה מאות סוכנויות, ומתעדכנים כמה פעמים ביום. מחיר עלול להשתנות או להיעלם לפני ההזמנה — תמיד בדקו באתר לפני תשלום.",
    sourceCode: "קוד פתוח",
  },

  ru: {
    dir: "ltr",
    locale: "ru-RU",
    label: "Русский",
    title: "Дешёвые рейсы из Израиля",
    tagline: "Аномально низкие цены на билеты из Тель-Авива, найденные автоматически.",
    description:
      "Мониторинг цен на авиабилеты из Израиля: статистически необычные цены и ошибочные тарифы со ссылкой на покупку.",

    updated: "Обновлено",
    findings: "находок",
    destinations: "направлений с ценами",
    routesTracked: "маршрутов в истории",
    observations: "наблюдений цен",

    searchPlaceholder: "Поиск по городу или коду аэропорта…",
    allTiers: "Все уровни",
    sortRecent: "Сначала новые",
    sortDiscount: "По размеру скидки",
    sortPrice: "По цене",
    directOnly: "Только прямые",

    tierGood: "Хорошая цена",
    tierGreat: "Отличная цена",
    tierExceptional: "Исключительная цена",
    tierErrorFare: "Похоже на ошибочный тариф",

    dealsEmpty:
      "Аномально низких цен пока нет. Детектору нужна история за несколько дней, чтобы отличить скидку от обычной цены — а пока смотрите текущие лучшие цены ниже.",
    nothingMatches: "Ничего не найдено по этому фильтру.",
    noPricesYet: "Сканер ещё не собрал ни одной цены.",
    noPriceFor: "Цену на {place} мы ещё не собрали. Можно искать напрямую:",
    searchItOn: "Искать на",
    dateFrom: "Вылет с",
    dateTo: "Возврат до",
    budget: "До",
    anyBudget: "любая цена",
    reset: "Сбросить",
    allCountries: "Все страны",
    focusHeading: "{place}: цены во времени",
    monthChartTitle: "Цена по месяцам вылета",
    cheapestMonth: "Дешевле всего в {month} — {price}",
    historyHeading: "Как менялась цена",
    historyTooShort: "Копим историю с {date}. График станет содержательным через неделю-другую.",
    heatmapHeading: "Куда и когда дёшево",
    heatmapHint: "Каждая клетка — самая низкая цена на направление в этом месяце. Зелёный = дёшево.",
    noDataForFilter: "В эти даты рейсов не найдено.",

    currentHeading: "Самые дешёвые сейчас",
    currentHint:
      "Лучшая найденная цена по каждому направлению за последние трое суток. Это не обязательно скидка — просто то, что дешевле всего прямо сейчас.",
    routesHeading: "Наблюдаемые маршруты",
    routesEmpty: "Пока нет накопленных маршрутов.",

    buy: "Купить",
    buyExact: "Купить по этой цене",
    compare: "Сравнить:",
    seller: "Продавец:",
    exactNote: "Ссылка ведёт именно на этот тариф",
    searchNote: "Ссылка ведёт на поиск — цена может отличаться",

    nights: "ноч.",
    direct: "без пересадок",
    stops: "пересадок:",
    oneWay: "в одну сторону",
    datesTbd: "даты уточняются",
    perPerson: "за человека, туда-обратно",
    noHistoryBasis: "оценка без истории",

    colDestination: "Направление",
    colType: "Тип",
    colObservations: "Наблюдений",
    colCheapest: "Минимум",
    colAverage: "Средняя",
    roundTrip: "туда-обратно",

    errorFareWarning:
      "Ошибочные тарифы живут часы. Бронировать сразу, отели и планы — только после подтверждения от авиакомпании.",
    loadError: "Не удалось загрузить данные",
    loading: "Загрузка…",
    footer:
      "Цены собираются автоматически из Aviasales, который сравнивает сотни агентств, и обновляются несколько раз в день. Тариф может измениться или исчезнуть до бронирования — всегда проверяйте цену перед оплатой.",
    sourceCode: "Открытый код",
  },

  en: {
    dir: "ltr",
    locale: "en-GB",
    label: "English",
    title: "Cheap flights from Israel",
    tagline: "Unusually low fares out of Tel Aviv, found automatically around the clock.",
    description:
      "Flight price monitoring for Israel: statistically abnormal fares and pricing errors, each with a link to buy.",

    updated: "Updated",
    findings: "findings",
    destinations: "destinations priced",
    routesTracked: "routes tracked",
    observations: "price checks",

    searchPlaceholder: "Search by city or airport code…",
    allTiers: "All tiers",
    sortRecent: "Newest first",
    sortDiscount: "By discount",
    sortPrice: "By price",
    directOnly: "Direct only",

    tierGood: "Good price",
    tierGreat: "Great price",
    tierExceptional: "Exceptional price",
    tierErrorFare: "Likely a pricing error",

    dealsEmpty:
      "No abnormal fares yet. The detector needs a few days of history before it can tell a discount from a normal price — meanwhile, see the cheapest fares right now below.",
    nothingMatches: "Nothing matches this filter.",
    noPricesYet: "No prices collected yet.",
    noPriceFor: "No fare collected for {place} yet. Search it directly:",
    searchItOn: "Search on",
    dateFrom: "Leaving after",
    dateTo: "Back before",
    budget: "Up to",
    anyBudget: "any price",
    reset: "Reset",
    allCountries: "All countries",
    focusHeading: "{place}: prices over time",
    monthChartTitle: "Price by month of departure",
    cheapestMonth: "Cheapest in {month} — {price}",
    historyHeading: "How the price moved",
    historyTooShort: "Collecting history since {date}. The chart gets meaningful after a week or two.",
    heatmapHeading: "Where and when it is cheap",
    heatmapHint: "Each cell is the lowest fare to that destination in that month. Green = cheap.",
    noDataForFilter: "No flights within those dates.",

    currentHeading: "Cheapest right now",
    currentHint:
      "The lowest fare found per destination over the last three days. Not necessarily a discount — just the cheapest available now.",
    routesHeading: "Routes tracked",
    routesEmpty: "No routes collected yet.",

    buy: "Book",
    buyExact: "Book this fare",
    compare: "Compare:",
    seller: "Sold by",
    exactNote: "Links straight to this fare",
    searchNote: "Links to a search — the price may differ",

    nights: "nights",
    direct: "non-stop",
    stops: "stops:",
    oneWay: "one way",
    datesTbd: "dates to be confirmed",
    perPerson: "per person, round trip",
    noHistoryBasis: "estimate without history",

    colDestination: "Destination",
    colType: "Type",
    colObservations: "Checks",
    colCheapest: "Lowest",
    colAverage: "Average",
    roundTrip: "round trip",

    errorFareWarning:
      "Pricing errors disappear within hours. Book immediately, and hold off on hotels until the airline confirms.",
    loadError: "Could not load the data",
    loading: "Loading…",
    footer:
      "Prices are collected automatically from Aviasales, which compares hundreds of agencies, and refresh several times a day. A fare can change or vanish before you book — always check on the seller's site before paying.",
    sourceCode: "Source code",
  },
};

const COMPARE_LABELS = { skyscanner: "Skyscanner", google: "Google Flights", kiwi: "Kiwi" };

const DEFAULT_LANG = "he";

function pickLang() {
  const fromQuery = new URLSearchParams(location.search).get("lang");
  const stored = (() => {
    try { return localStorage.getItem("lang"); } catch { return null; }
  })();
  const candidate = fromQuery || stored || (navigator.language || "").slice(0, 2);
  return I18N[candidate] ? candidate : DEFAULT_LANG;
}

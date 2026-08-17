"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import date, timedelta

from . import watchlist as watchlist_module
from .config import Settings
from .geo import SITE_LANGS, Geo
from .models import TIER_EXCEPTIONAL, Deal, Offer
from .notify import build_notifiers
from .notify.console import ConsoleNotifier
from .providers.travelpayouts import TravelpayoutsProvider
from .publish import build_payload, publisher_from
from .runner import run_scan
from .storage import Storage

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _build(settings: Settings) -> tuple[TravelpayoutsProvider, Storage, Geo]:
    settings.ensure_dirs()
    provider = TravelpayoutsProvider(
        token=settings.tp_token,
        currency=settings.currency,
        marker=settings.tp_marker,
        timeout=settings.http_timeout,
        market=settings.market,
    )
    return provider, Storage(settings.db_path), Geo(settings.cache_dir, langs=SITE_LANGS)


# -- commands ---------------------------------------------------------------


def cmd_scan(args: argparse.Namespace, settings: Settings) -> int:
    provider, storage, geo = _build(settings)
    entries = watchlist_module.load(args.watchlist or settings.watchlist_path)
    notifiers = [ConsoleNotifier(geo)] if args.dry_run else build_notifiers(settings, geo)

    logger.info("scanning %d watchlist entries", len(entries))
    report = run_scan(
        settings, provider, storage, entries, notifiers, geo=geo, dry_run=args.dry_run
    )
    print(f"\nИтог: {report.summary()}")
    for error in report.errors:
        print(f"  ! {error}")

    removed = storage.prune(settings.keep_history_days, settings.keep_rollup_days)
    if removed:
        logger.info("pruned %d observations older than %d days", removed, settings.keep_history_days)

    # Refresh the public site even when nothing was alerted: the page also
    # shows collected history, and a stale "generated_at" reads as a dead
    # service.
    if not args.dry_run:
        publisher = publisher_from(settings)
        if publisher:
            publisher.publish(build_payload(storage, geo, settings.currency,
                                            marker=settings.tp_marker))

    storage.close()
    return 1 if report.errors and not report.offers_seen else 0


def cmd_watch(args: argparse.Namespace, settings: Settings) -> int:
    """Scan forever on an interval.

    The interval is jittered because a fixed schedule means every scan lands
    at the same minute past the hour, which both looks like a bot to the API
    and systematically misses fares published just after each sweep.
    """
    interval = settings.scan_interval_minutes * 60
    logger.info("watch mode: scanning every ~%d minutes", settings.scan_interval_minutes)
    while True:
        try:
            cmd_scan(args, settings)
        except KeyboardInterrupt:
            logger.info("stopped")
            return 0
        except Exception:
            logger.exception("scan failed, continuing")
        delay = interval * random.uniform(0.85, 1.15)
        logger.info("next scan in %.0f min", delay / 60)
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("stopped")
            return 0


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    """Verify the token, the API shape and the notifier wiring in one pass."""
    ok = True
    print(f"Валюта: {settings.currency.upper()}   БД: {settings.db_path}")

    if not settings.tp_token:
        print("✗ TRAVELPAYOUTS_TOKEN не задан")
        return 1
    print(f"✓ Токен задан ({settings.tp_token[:6]}…)")

    provider, storage, geo = _build(settings)

    try:
        offers = provider.city_directions(args.origin)
        print(f"✓ city-directions {args.origin}: {len(offers)} направлений")
        for offer in sorted(offers, key=lambda o: o.price)[:5]:
            print(
                f"    {offer.destination:>4}  {offer.price:>8.0f} {offer.currency.upper()}"
                f"  {offer.depart_date or '?'} → {offer.return_date or '—'}"
            )
    except Exception as exc:
        print(f"✗ city-directions не отвечает: {exc}")
        ok = False

    try:
        geo.load()
        km = geo.distance_km(args.origin, "BKK")
        print(f"✓ Справочник аэропортов загружен ({args.origin}→BKK ≈ {km:.0f} км)")
    except Exception as exc:
        print(f"✗ Справочник аэропортов недоступен: {exc}")
        ok = False

    notifiers = build_notifiers(settings, geo)
    print(f"✓ Каналы уведомлений: {', '.join(n.name for n in notifiers)}")

    stats = storage.stats()
    print(
        f"✓ История: {stats['observations']} наблюдений по {stats['routes']} маршрутам, "
        f"{stats['alerts']} отправленных алертов"
    )
    storage.close()
    return 0 if ok else 1


def cmd_stats(args: argparse.Namespace, settings: Settings) -> int:
    settings.ensure_dirs()
    storage = Storage(settings.db_path)
    stats = storage.stats()
    print(
        f"Наблюдений: {stats['observations']}   Маршрутов: {stats['routes']}   "
        f"Алертов: {stats['alerts']}"
    )
    print(f"Первое наблюдение: {stats['first_seen'] or '—'}\n")

    print("Самые наблюдаемые маршруты:")
    for row in storage.top_routes():
        print(
            f"  {row['origin']}→{row['destination']} ({row['trip_kind']}) "
            f"n={row['n']:<5} мин={row['cheapest']:.0f} "
            f"среднее={row['avg_price']:.0f} {row['currency'].upper()}"
        )

    recent = storage.recent_alerts(10)
    if recent:
        print("\nПоследние алерты:")
        for row in recent:
            print(
                f"  {row['sent_at'][:16]}  {row['origin']}→{row['destination']}  "
                f"{row['price']:.0f} {row['currency'].upper()} "
                f"(−{row['drop_pct']:.0%}, {row['tier']}, {row['basis']})"
            )
    storage.close()
    return 0


def cmd_publish(args: argparse.Namespace, settings: Settings) -> int:
    """Rebuild the site payload from the database and upload it."""
    settings.ensure_dirs()
    storage = Storage(settings.db_path)
    geo = Geo(settings.cache_dir, langs=SITE_LANGS)
    payload = build_payload(storage, geo, settings.currency, marker=settings.tp_marker)

    if args.stdout:
        import json

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        storage.close()
        return 0

    publisher = publisher_from(settings)
    if publisher is None:
        print("SITE_BUCKET не задан — публиковать некуда")
        storage.close()
        return 1

    ok = publisher.publish(payload)
    print(
        f"{'✓' if ok else '✗'} {len(payload['deals'])} находок, "
        f"{len(payload['routes'])} маршрутов → s3://{settings.site_bucket}/{settings.site_data_key}"
    )
    storage.close()
    return 0 if ok else 1


def cmd_test_notify(args: argparse.Namespace, settings: Settings) -> int:
    """Push one synthetic deal through every configured channel."""
    settings.ensure_dirs()
    geo = Geo(settings.cache_dir, langs=SITE_LANGS)

    today = date.today()
    offer = Offer(
        origin=args.origin,
        destination="BKK",
        price=199.0,
        currency=settings.currency,
        depart_date=today + timedelta(days=45),
        return_date=today + timedelta(days=59),
        transfers=1,
        airline="TK",
        source="test",
    )
    deal = Deal(
        offer=offer,
        baseline_price=620.0,
        drop_pct=0.68,
        z_score=4.2,
        tier=TIER_EXCEPTIONAL,
        basis="history",
        reason="тестовое уведомление, реальной цены за ним нет",
    )

    booking_url = f"https://www.aviasales.com/search/{offer.origin}0101BKK15011"
    for notifier in build_notifiers(settings, geo):
        result = notifier.send(deal, booking_url)
        print(f"{notifier.name}: {'✓ отправлено' if result else '✗ ошибка'}")
    return 0


# -- wiring -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight_radar", description="Мониторинг дешёвых авиабилетов"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--watchlist", help="путь к watchlist.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="один проход по списку наблюдения")
    scan.add_argument("--dry-run", action="store_true", help="только вывести в консоль")
    scan.set_defaults(func=cmd_scan)

    watch = sub.add_parser("watch", help="бесконечный цикл сканирования")
    watch.add_argument("--dry-run", action="store_true")
    watch.set_defaults(func=cmd_watch)

    doctor = sub.add_parser("doctor", help="проверить токен, API и каналы")
    doctor.add_argument("--origin", default="TLV")
    doctor.set_defaults(func=cmd_doctor)

    stats = sub.add_parser("stats", help="что накопилось в базе")
    stats.set_defaults(func=cmd_stats)

    publish = sub.add_parser("publish", help="выгрузить данные для сайта в S3")
    publish.add_argument("--stdout", action="store_true", help="напечатать JSON вместо загрузки")
    publish.set_defaults(func=cmd_publish)

    test = sub.add_parser("test-notify", help="отправить тестовое уведомление")
    test.add_argument("--origin", default="TLV")
    test.set_defaults(func=cmd_test_notify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    settings = Settings.from_env()
    if not hasattr(args, "dry_run"):
        args.dry_run = False
    if not hasattr(args, "watchlist"):
        args.watchlist = None
    try:
        return args.func(args, settings)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.error("%s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

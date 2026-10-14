"""Command-line entry point: ``logpipe run`` and friends."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterable, Iterator, Sequence
from typing import TYPE_CHECKING

from logpipe import __version__
from logpipe.config import Config, ConfigError, SinkConfig, load_config
from logpipe.inputs import read_records
from logpipe.parsers import ParseError, available_parsers
from logpipe.pipeline import Pipeline
from logpipe.sinks import available_sinks, build_sink
from logpipe.stages import available_stages, build_stage

if TYPE_CHECKING:
    from logpipe.aggregate import AggregateRow, Aggregator
    from logpipe.record import LogRecord

log = logging.getLogger("logpipe")


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="*", help="input files ('-' for stdin)")
    parser.add_argument("-c", "--config", help="path to logpipe.toml")
    parser.add_argument("-f", "--format", help="input format (see `logpipe formats`)")
    parser.add_argument("--strict", action="store_true", help="fail on unparseable lines")
    parser.add_argument("-v", "--verbose", action="count", default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logpipe", description=__doc__)
    parser.add_argument("--version", action="version", version=f"logpipe {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="parse, filter and ship logs")
    _add_input_args(run)
    run.add_argument("--min-level", help="drop records below this level")
    run.add_argument(
        "-o", "--output", choices=["text", "json"], help="write to stdout in this format"
    )

    sub.add_parser("formats", help="list input formats, stages and sinks")

    agg = sub.add_parser("aggregate", help="summarise logs per time window")
    _add_input_args(agg)
    agg.add_argument(
        "-w", "--window", type=float, default=60.0, help="window width in seconds (default: 60)"
    )
    agg.add_argument(
        "-g", "--group-by", default="", help="comma-separated fields to group by, e.g. level,host"
    )
    agg.add_argument("-m", "--metric", help="numeric field to summarise, e.g. request_time")
    agg.add_argument(
        "-p", "--percentiles", default="50,90,99", help="percentiles reported for --metric"
    )
    agg.add_argument(
        "--lateness", type=float, default=0.0, help="seconds to wait for out-of-order records"
    )
    agg.add_argument("--report", choices=["table", "jsonl", "csv"], default="table")
    agg.add_argument("--csv-path", help="output file for --report csv")
    return parser


def _resolve_config(args: argparse.Namespace) -> Config:
    cfg = load_config(args.config) if args.config else Config()
    if args.format:
        cfg.input.format = args.format
    if args.paths:
        cfg.input.paths = list(args.paths)
    if args.strict:
        cfg.input.strict = True
    if getattr(args, "min_level", None):
        cfg.stages.insert(0, {"type": "level", "min": args.min_level})
    if getattr(args, "output", None):
        cfg.sink = SinkConfig(type="stdout", options={"format": args.output})
    return cfg


def _configure_logging(level: str, verbose: int) -> None:
    if verbose >= 2:
        level = "debug"
    elif verbose == 1:
        level = "info"
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    _configure_logging(cfg.log_level, args.verbose)
    stages = [build_stage(spec) for spec in cfg.stages]
    sink = build_sink(cfg.sink.type, **cfg.sink.options)
    records = read_records(
        cfg.input.paths, cfg.input.format, strict=cfg.input.strict, encoding=cfg.input.encoding
    )
    stats = Pipeline(stages, sink).run(records)
    if stats.read == 0:
        log.warning("no records read from %s", ", ".join(cfg.input.paths))
    return 0


def _cmd_formats(args: argparse.Namespace) -> int:
    print("input formats:")
    for name, description in available_parsers().items():
        print(f"  {name:<10} {description}")
    print("stages:  " + ", ".join(available_stages()))
    print("sinks:   " + ", ".join(available_sinks()))
    return 0


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _aggregate(
    aggregator: Aggregator, records: Iterable[LogRecord], *, live: bool
) -> Iterator[AggregateRow]:
    """Feed records through the aggregator, yielding rows as windows close.

    For live input (stdin) windows are also closed on wall-clock time, so a
    window is reported once it is over even if the event-time watermark lags
    behind, e.g. because the source only logs sporadically.
    """
    last_tick = time.monotonic()
    for record in records:
        yield from aggregator.add(record)
        if live and time.monotonic() - last_tick >= 1.0:
            last_tick = time.monotonic()
            yield from aggregator.flush_expired()
    yield from aggregator.finish()


def _cmd_aggregate(args: argparse.Namespace) -> int:
    # Imported lazily to keep `logpipe run` start-up fast.
    from logpipe.aggregate import Aggregator
    from logpipe.aggregate.report import render_table, write_csv, write_jsonl

    cfg = _resolve_config(args)
    _configure_logging(cfg.log_level, args.verbose)
    if args.report == "csv" and not args.csv_path:
        raise ValueError("--report csv requires --csv-path")

    aggregator = Aggregator(
        args.window,
        group_by=_split_list(args.group_by),
        metric=args.metric,
        percentiles=[float(p) for p in _split_list(args.percentiles)],
        allowed_lateness=args.lateness,
    )
    records: Iterable[LogRecord] = read_records(
        cfg.input.paths, cfg.input.format, strict=cfg.input.strict, encoding=cfg.input.encoding
    )
    for spec in cfg.stages:
        records = build_stage(spec).process(records)
    rows = _aggregate(aggregator, records, live="-" in cfg.input.paths)

    if args.report == "jsonl":
        write_jsonl(rows, sys.stdout, flush=True)
    elif args.report == "csv":
        written = write_csv(rows, args.csv_path)
        log.info("wrote %d row(s) to %s", written, args.csv_path)
    else:
        render_table(rows, sys.stdout)

    if aggregator.late_records:
        log.warning(
            "ignored %d record(s) that arrived after their window closed",
            aggregator.late_records,
        )
    if args.metric and aggregator.non_numeric:
        log.warning(
            "%d record(s) had a missing or non-numeric %s", aggregator.non_numeric, args.metric
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "run": _cmd_run,
        "formats": _cmd_formats,
        "aggregate": _cmd_aggregate,
    }
    try:
        return handlers[args.command](args)
    except (ConfigError, ParseError, ValueError) as exc:
        print(f"logpipe: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

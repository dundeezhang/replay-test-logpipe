"""Command-line entry point: ``logpipe run`` and friends."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from logpipe import __version__
from logpipe.config import (
    Config,
    ConfigError,
    SinkConfig,
    apply_env_overrides,
    describe,
    load_config,
)
from logpipe.inputs import read_records
from logpipe.parsers import ParseError, available_parsers
from logpipe.pipeline import Pipeline
from logpipe.sinks import available_sinks, build_sink
from logpipe.stages import available_stages, build_stage

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
    return parser


def _resolve_config(args: argparse.Namespace) -> Config:
    cfg = load_config(args.config) if args.config else Config()
    apply_env_overrides(cfg)
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
    log.info("effective configuration: %s", describe(cfg))
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "run": _cmd_run,
        "formats": _cmd_formats,
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

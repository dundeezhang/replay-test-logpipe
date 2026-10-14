# logpipe

Composable log ingestion and processing for Python 3.12+. `logpipe` reads raw
log lines, parses them into structured records, runs them through a chain of
stages (filters and transforms) and writes the result to a sink.

It has no runtime dependencies and is meant to be embedded in small agents,
cron jobs and CI tooling as well as used from the command line.

## Install

```sh
pip install -e ".[dev]"
```

## Quick start

```sh
# Pretty-print warnings and above from the local syslog
logpipe run -f syslog --min-level warning /var/log/syslog

# Normalise JSON application logs read from stdin
cat app.log | logpipe run -f jsonl -o json
```

Run `logpipe formats` to list the input formats, stages and sinks available in
your install.

## Input formats

| Name       | Description                                                   |
| ---------- | ------------------------------------------------------------- |
| `combined` | nginx/Apache combined or common access log                    |
| `jsonl`    | One JSON object per line (`timestamp`/`time`/`ts`, `message`) |
| `syslog`   | BSD syslog (RFC 3164), with or without the `<PRI>` prefix     |

Lines that fail to parse are skipped and counted; pass `--strict` to stop at
the first bad line instead.

The `combined` parser maps HTTP status codes to levels (5xx is `error`, 4xx is
`warning`) and stores the request, status, size, referer and user agent in the
record fields. An nginx `$request_time` appended to the line is captured as
`request_time`, and Apache's `vhost_combined` layout is supported with the
`vhost = true` option.

## Stages

Stages are applied in the order they appear in the config file.

| Type    | Options                                     | Effect                           |
| ------- | ------------------------------------------- | -------------------------------- |
| `level` | `min`                                       | drop records below `min`         |
| `match` | `pattern`, `field`, `invert`, `ignore_case` | keep records whose field matches |

`field` accepts record attributes (`message`, `source`, `host`) or a dotted
path into the parsed fields, e.g. `http.status`.

## Sinks

Exactly one sink is configured per pipeline.

| Type     | Options                      |
| -------- | ---------------------------- |
| `file`   | `path`, `format`, `encoding` |
| `stdout` | `format` (`text` or `json`)  |

Sinks are flushed and closed when the input is exhausted, including when the
pipeline stops because of an error.

## Configuration

```toml
log_level = "info"

[input]
format = "syslog"
paths = ["/var/log/syslog"]

[[stages]]
type = "level"
min = "warning"

[sink]
type = "file"
path = "/var/lib/logpipe/out.jsonl"
```

Command-line flags take precedence over the config file.

## Development

```sh
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

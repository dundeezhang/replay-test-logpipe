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

| Name     | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `jsonl`  | One JSON object per line (`timestamp`/`time`/`ts`, `message`) |
| `syslog` | BSD syslog (RFC 3164), with or without the `<PRI>` prefix     |

Lines that fail to parse are skipped and counted; pass `--strict` to stop at
the first bad line instead.

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

## Aggregation

`logpipe aggregate` summarises records per fixed time window instead of
forwarding them. Windows are aligned to the Unix epoch in UTC, so 60 second
windows always start on the minute.

```sh
# Requests per minute and latency percentiles, split by status class
logpipe aggregate -f combined -w 60 -g status -m request_time access.log

# Error counts per host in 5 minute windows, as JSON lines
logpipe aggregate -f syslog -w 300 -g host --report jsonl /var/log/syslog
```

| Option          | Meaning                                                      |
| --------------- | ------------------------------------------------------------ |
| `-w/--window`   | window width in seconds; must divide a day evenly            |
| `-g/--group-by` | comma-separated record fields (`level`, `host`, `http.code`) |
| `-m/--metric`   | numeric field to summarise (count, sum, min, max, mean)      |
| `-p`            | percentiles to report for the metric (default `50,90,99`)    |
| `--lateness`    | seconds to keep a window open for out-of-order records       |
| `--report`      | `table` (default), `jsonl`, or `csv` with `--csv-path`       |

A window is reported once a record more than `--lateness` seconds past its end
has been seen; records that arrive after that are counted and ignored. When
reading from stdin, windows are also closed on wall-clock time so live tails
keep producing output.

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

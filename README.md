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
| `dedup` | `window`, `max_keys`                        | suppress repeats within `window` |
| `level` | `min`                                       | drop records below `min`         |
| `match` | `pattern`, `field`, `invert`, `ignore_case` | keep records whose field matches |

`field` accepts record attributes (`message`, `source`, `host`) or a dotted
path into the parsed fields, e.g. `http.status`.

## Sinks

Exactly one sink is configured per pipeline.

| Type     | Options                                                        |
| -------- | -------------------------------------------------------------- |
| `file`   | `path`, `format`, `encoding`                                   |
| `http`   | `url`, `token_env`, `batch_size`, `spool_dir`, ... (see below) |
| `stdout` | `format` (`text` or `json`)                                    |

### HTTP sink

The `http` sink POSTs records to a collector in batches, as gzip-compressed
newline-delimited JSON by default (`encoding = "json"` sends a JSON array
instead). A batch is sent when it reaches `batch_size` records (default 500),
`batch_bytes` bytes (default 1 MB) or `flush_interval` seconds (default 5).

The bearer token is read from the environment variable named by `token_env`
(default `LOGPIPE_TOKEN`); extra request headers can be set in a
`[sink.headers]` table.

Network errors and `408`, `425`, `429` and `5xx` responses are retried with
exponential backoff (capped at `max_backoff` seconds, default 30), honouring
`Retry-After`. By default the sink keeps retrying until the collector accepts
the batch; set `max_attempts` to give up earlier. Batches that cannot be delivered are written to `spool_dir` if it is
set (and dropped otherwise) and can be re-sent later with
`HttpSink.replay_spool()`. See [`examples/http-shipper.toml`](examples/http-shipper.toml).

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

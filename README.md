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

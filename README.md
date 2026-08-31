# BastionCam

Local searchable history for every Zellij terminal pane, with full-text and
semantic search, LLM-generated episode summaries, and snapshot playback.

## Setup

Python 3.11+ and Zellij 0.45+ are required. Install dependencies in a virtual
environment:

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

Start the collector and web interface manually:

```bash
cd /home/shaman007/git/bastioncam
.venv/bin/python -m bastioncam.cli --db ./history.db run --interval 5
```

Open <http://127.0.0.1:8787>. Only changed viewports are stored, so an idle
terminal does not grow the database.

On first open, `/setup` creates the initial administrator. Browser access then
requires a username and password. Every account currently has the single
`admin` role and can add another administrator with a chosen password under
`/admin/users`. Passwords are stored as salted scrypt hashes; browser sessions
use seven-day HttpOnly, SameSite cookies and CSRF tokens on administrative
forms. The health check and JWT-authenticated ingestion endpoint do not use the
browser session.

## Automatic startup

Kitty starts Zellij through `~/.local/bin/zellij-with-history`. The wrapper asks
the user systemd instance to start exactly one `bastioncam.service` with the
first Zellij invocation. The persistent database is
`/home/shaman007/git/bastioncam/history.db`.

Related services:

- `bastioncam.service` records panes and serves the UI.
- `bastioncam-enricher.service` creates episode, hourly, and daily summaries.
- `bastioncam-ollama.service` serves local models from `~/.ollama`.

The Ollama service uses the official CUDA-capable bundle under
`~/.local/opt/ollama-official`, because the Fedora package does not include a
CUDA backend. No manual `ollama serve` invocation is required.

## Split collector/server deployment

The local collector can send snapshots to a remote server while retaining an
on-disk outbox. Failed deliveries remain queued and are retried on the next
collection cycle:

First open `/admin/collectors` on the server, enter a human-readable collector
name, and generate a JWT. The token is shown once. Store it in a mode-0600
environment file:

```bash
install -d -m 700 ~/.config/bastioncam
printf 'BASTIONCAM_TOKEN=%s\n' 'paste-generated-token-here' \
  > ~/.config/bastioncam/collector.env
chmod 600 ~/.config/bastioncam/collector.env
```

```bash
set -a; . ~/.config/bastioncam/collector.env; set +a
.venv/bin/python -m bastioncam.cli \
  --db ~/.local/share/bastioncam/collector.db \
  collect \
  --interval 5 \
  --server-url http://bastioncam.w386.k8s.my.lan
```

The remote server requires the JWT as a Bearer token on `POST /api/ingest`, uses
the verified collector name as the session namespace, performs secret filtering
again, stores snapshots, serves the UI, and runs enrichment. A standalone
collector unit template is available under `deploy/collector/`.

Collectors send a protocol-v1 heartbeat every 30 seconds. The heartbeat reports
hostname, operating system, collector and terminal-backend versions, queue depth,
and the most recent delivery error, then receives the current configuration
revision and pause state. The collector admin page can set owner and labels,
pause/resume collection, temporarily disable credentials, or permanently revoke
a collector. Uploads carrying an unsupported protocol, a stale configuration
revision, or a paused identity are rejected without storing their payload.

## Container image

Build the image locally:

```bash
podman build -t bastioncam:latest .
```

Pushes to `main` publish AMD64 and ARM64 images to
`ghcr.io/shaman007/bastioncam`. Cluster deployment is managed separately by the
`home-k3s` GitOps repository. Its configured Ollama endpoint must provide
`qwen3:4b` and `nomic-embed-text` before enrichment will succeed.

The broader product backlog and proposed implementation order are tracked in
[`TODO.md`](TODO.md).

View logs with:

```bash
journalctl --user -u bastioncam.service
journalctl --user -u bastioncam-enricher.service
journalctl --user -u bastioncam-ollama.service
```

## Commands

```bash
.venv/bin/python -m bastioncam.cli --db ./history.db collect-once
.venv/bin/python -m bastioncam.cli --db ./history.db stats
.venv/bin/python -m bastioncam.cli --db ./history.db serve
.venv/bin/python -m bastioncam.cli --db ./history.db enrich --limit 20
.venv/bin/python -m bastioncam.cli --db ./history.db scrub
```

`scrub` irreversibly redacts detected secrets already stored in the database.

## Search and enrichment

SQLite FTS5 provides exact search. `nomic-embed-text` provides semantic
similarity, and `qwen3:4b` parses natural-language time ranges and creates
English summaries. Query text may be multilingual, but UI metadata and generated
summaries are always English.

Snapshots from one pane are grouped into episodes. Enrichment is asynchronous:
collection and full-text search remain available if Ollama is unavailable.
Hourly summaries refresh no more than every ten minutes, and the current daily
summary refreshes no more than once per hour.

The calendar is the `/` home page, with search at the top. Activity days are
marked with snapshot counts; selecting a day shows its daily summary followed by
chronological hour-by-hour summaries. Each hourly episode count links to the
episodes overlapping that hour.

## Playback

Playback reconstructs textual snapshots rather than the exact ANSI or keystroke
stream. It supports play/pause, 1–10x speed, a timeline slider, time navigation,
and highlighting of newly appeared lines.

## Secret filtering

Content is filtered before storage with Yelp's Apache-2.0 `detect-secrets`, plus
terminal-specific rules for assignments, authorization headers, known token
formats, and PEM blocks. Generic Base64/hex entropy and public-IP detectors are
disabled to avoid destroying ordinary terminal output. Detection lowers risk but
cannot guarantee that every possible secret will be found.

## Current limitations

- Complete Zellij scrollback is recorded with every changed snapshot. This
  improves command capture for fast-output processes but can grow the SQLite
  database quickly. Retention controls and PostgreSQL storage are planned.
- Resurrection-only Zellij sessions do not expose live panes.
- The HTTP server listens on localhost by default.

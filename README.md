# moviedownloader

A movie and series search and download manager. Python 3.14+, FastAPI for the
API and asynchronous transfers, Flask for the interface, and SQLite for history.
No Node build, Redis, database server, or API key is needed.

## Run

```sh
./run.sh
```

The launcher installs missing dependencies using `uv`, starts at port **8765**,
and increments the port if it is occupied. Open the address printed in the terminal.

```sh
./run.sh               # Start at 8765 (or MOVIEBOX_PORT from the environment/.env)
./run.sh 9000          # Start at 9000; try 9001, 9002, ... if needed
./run.sh --port 9000   # Same as above
./run.sh -p 9000       # Short option
./run.sh --dev         # Development mode with automatic server reload
./run.sh --dev -p 9000 # Development mode with a chosen starting port
./run.sh --help        # Show usage
```

On Windows, use `run.bat` from Command Prompt or `.\run.bat` from PowerShell:

```powershell
.\run.bat                  # Normal mode
.\run.bat --dev            # Reload and automatically detect the network IP
.\run.bat --dev --port 9000 # Choose a starting port
.\run.bat --help
```

Both launchers require `uv` on your PATH and use the same Python startup logic.
In dev mode, your current network IP is detected each time you start the app;
you do not need to enter an IP or edit a configuration file. For example,
`./run.sh --dev` and `.\run.bat --dev` both print local and network URLs.

The script works from any working directory and forwards Ctrl+C to the server.
Ctrl+C gracefully closes downloads and the database and exits without a traceback.
In development mode it also stops the reload worker and releases the listening socket.
The selected port is reserved until Uvicorn takes it over, avoiding a port-selection
race. An explicit command-line port overrides `MOVIEBOX_PORT`. If no port is
available through 65535, startup fails with an explanation. You can also use
`uv run python main.py` with the same arguments.

Development mode watches Python, HTML, CSS, and JavaScript files. The server
binds to `0.0.0.0` and prints local and network links, for example:

```text
Local:   http://127.0.0.1:8765
Network: http://192.168.1.42:8765
```

Open the network link on another device connected to the same network. The printed
IP is detected from your computer's network interfaces; additional detected
addresses get their own network links. If none can be detected, the launcher
reports that network access is unavailable. Allow incoming connections through
your computer's firewall if it prompts. Normal mode keeps its configured local bind.

The server restarts on edits and keeps the same selected port. Refresh your browser to see
page and style changes; the browser does not refresh automatically. Download and
database directories are excluded from watching. Reloading stops active downloads;
use Retry to start them again after the server restarts.

Search by title, select a movie or series, and choose an available quality. For
series, choose a season and a single episode or **All episodes in this season**.
The app resolves the video URL and adds the selection to the download queue.
Whole seasons are queued together or rejected together if the queue has too
little capacity. Episodes without the chosen quality report a failure; the app
does not silently substitute another episode or quality.

Files are saved in `downloads/`. **Save file** copies a completed download to your
browser's chosen location; the original stays on the computer running the server.
Available subtitle languages appear with the qualities. **Save subtitles**
downloads the selected SRT file separately to your browser. The optional
**Add a movie by URL** section still supports direct media links.

Supported inputs include MP4, MKV, WebM, MOV, AVI, M4V, MPEG, and TS files. A URL
without an extension also works when the server returns a video content type.
Use content you have permission to download. Moviebox MP4 sources are supported;
HLS/DASH playlists, torrents, and DRM-protected or VIP-locked streams are not.
Some titles may have no usable source in a particular region or at a particular time.

## How it works

Transfers stream in 256 KiB chunks without loading entire movies into memory.
Three transfers can run concurrently by default; others wait. Network connections
are pooled, disk writes run off the event loop, and progress is persisted at most
twice per second. The interface polls once per second during active downloads
and slows down when idle. Actual throughput depends on the source and connection;
there is no benchmark claim or artificial speed multiplier.

Files use unique job IDs to prevent collisions. A temporary `.part` file becomes
available only after a successful transfer. Retry resumes a retained partial file
when the source provides an ETag or Last-Modified validator and honors HTTP range
requests. If the server sends a full response instead, the file restarts safely
rather than appending a second copy. Invalid ranges are rejected. Partials without
a validator are discarded. Interrupted jobs are marked failed at startup and await
Retry. Download history and searched title metadata survive in `data/moviebox.sqlite3`.

Catalog requests acquire a guest session automatically. Search results and player
metadata use bounded, short-lived caches. Title metadata is persisted so open
result cards keep working after development reloads. Signed video URLs are
refreshed when each queued download starts and again on retry.

The current `moviebox-api` PyPI wheel was checked on Python 3.14: release 0.6.0
contains only a greeting stub, without search or download functions. This app
therefore uses a dedicated async client for the Moviebox BFF endpoints instead.
Protocol references: [Moviebox-API](https://github.com/faisaljs/Moviebox-API) and
the user's [original reference](https://github.com/walterwhite-69/Moviebox-API).

## Project layout

```text
run.sh                        # Shell launcher, passes optional arguments
run.bat                       # Windows launcher with the same arguments
main.py                       # Python entry point
moviebox_app/
  cli.py                      # Port selection and Uvicorn startup
  launcher_network.py         # Development network address discovery
  app.py                      # Application factory and lifespan
  config.py                   # Validated environment settings
  models.py                   # Job states and request validation
  api/
    catalog.py                # Search, details, episodes, sources, subtitle endpoints
    routes.py                 # JSON endpoints and completed file delivery
    security.py               # Same-origin browser boundary and headers
  downloads/
    manager.py                # Concurrency, cancellation, retries, lifecycle
    network.py                # Public URL and connection-time DNS checks
    transfer.py               # Streaming, response validation, byte limits
    resume.py                 # Content-Range and representation validation
  catalog/
    client.py                 # Async provider transport and guest-token lifecycle
    service.py                # Search, source resolution, expiring-link refresh
    details.py                # Movie detection and valid season/episode selection
    subtitles.py              # Subtitle discovery and bounded retrieval
    cache.py                  # Bounded TTL caches
    models.py                 # Catalog request/response models
    repository.py             # Persistent title metadata across reloads
  storage/
    paths.py                  # Safe names and unique file paths
    repository.py             # SQLite history and restart recovery
  web/
    __init__.py               # Flask application factory
    templates/index.html      # Page structure
    static/app.css            # Responsive styles
    static/app.js             # Form actions, filters, adaptive polling
    static/api.js             # HTTP requests and error handling
    static/queue.js           # Download list rendering
    static/movie-search.js    # Title searches and result pagination
    static/movie-card.js      # Result cards and movie/series selection
    static/episode-picker.js  # Season and episode selection
    static/source-picker.js   # Quality, download, and subtitle controls
    static/format.js          # Shared text rendering and byte formatting
tests/                        # API, queue, transfer, network, persistence tests
```

The original Python 2 files (`moviebox.py`, `file_receive.py`, `settings.py`,
`settings_gunicorn.py`, `truncate.py`, `moviebox.api`, `moviebox.sql`, and
`requirements.txt`) remain as legacy reference. They are not imported or used by
this application. The legacy `settings.py` is excluded from Git because it
contains local credentials. Use `uv sync`, not the legacy requirements file.

## Configuration

Copy `.env.example` to `.env` and adjust the values, or set environment variables.
Paths are relative to the directory where you start the app.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MOVIEBOX_HOST` | `127.0.0.1` | Local bind address |
| `MOVIEBOX_PORT` | `8765` | Starting HTTP port (increments when occupied) |
| `MOVIEBOX_DATA_DIR` | `./data` | SQLite history directory |
| `MOVIEBOX_DOWNLOAD_DIR` | `./downloads` | Download directory |
| `MOVIEBOX_CONCURRENCY` | `3` | Simultaneous transfers (1–16) |
| `MOVIEBOX_MAX_QUEUE` | `100` | Waiting capacity, in addition to active slots |
| `MOVIEBOX_MAX_FILE_BYTES` | `21474836480` | Per-file limit: 20 GiB |
| `MOVIEBOX_CHUNK_SIZE` | `262144` | Buffer size in bytes |
| `MOVIEBOX_CONNECT_TIMEOUT` | `15` | Connection timeout in seconds |
| `MOVIEBOX_READ_TIMEOUT` | `45` | Timeout between incoming chunks |
| `MOVIEBOX_CATALOG_API_BASE` | `https://h5-api.aoneroom.com/wefeed-h5api-bff` | Moviebox BFF endpoint |
| `MOVIEBOX_CATALOG_HOST` | `moviebox.ph` | Catalog host selector |

Run **one Uvicorn worker**. The queue and cancellation handles belong to one
process. There is no authentication: use development network sharing on a trusted
network. Accepted request hosts are `localhost`, `127.0.0.1`, and `[::1]`;
development mode also accepts detected network IPs. `MOVIEBOX_ALLOWED_HOSTS` can
override the base allowlist using a JSON array of hostnames or IPs.
Private source addresses, nonstandard source ports, cross-origin browser requests,
and redirects into private networks are blocked. DNS checks happen on the
addresses actually used for outbound connections. Source URLs can contain signed
tokens; they are kept in the local database and omitted from API responses.

The history API is paginated. The interface shows the newest 50 jobs and can load
up to 200; use the API's `offset` parameter for older history. No global disk quota
or retention policy is applied: remove old files manually when needed.

## API

| Method | Path | Action |
| --- | --- | --- |
| GET | `/api/health` | Server status |
| GET | `/api/movies/search?q=Sintel&page=1` | Search movies and series |
| GET | `/api/movies/{id}/details` | Title details and available seasons |
| GET | `/api/movies/{id}/sources?season=0&episode=0` | MP4 qualities, sizes, and subtitle languages |
| POST | `/api/movies/{id}/download` | Queue `{ "source_id": "…", "season": 0, "episode": 0, "all_episodes": false }` |
| GET | `/api/movies/{id}/subtitles/{language}?season=0&episode=0` | Retrieve selected subtitles |
| GET | `/api/downloads?limit=50&offset=0` | Saved history, newest first |
| POST | `/api/downloads` | Queue `{ "url": "https://…/movie.mp4", "title": "Optional" }` |
| GET | `/api/downloads/{id}` | Status, bytes, speed, progress, errors |
| POST | `/api/downloads/{id}/cancel` | Cancel queued or active job |
| POST | `/api/downloads/{id}/retry` | Retry/resume failed or cancelled job |
| GET | `/api/downloads/{id}/file` | Retrieve a completed file |
| GET | `/openapi.json` | API schema |

The Flask app is mounted after the API using
[`a2wsgi`, as documented by FastAPI](https://fastapi.tiangolo.com/advanced/wsgi/).
The UI uses local scripts, styles, and system fonts. Posters are loaded from
the URLs supplied by Moviebox.

## Checks

```sh
uv run pytest -q
uv run ruff check moviebox_app tests main.py
uv run ruff format --check moviebox_app tests main.py
```

Tests use deterministic source responses, a temporary loopback HTTP server,
and temporary directories; they do not download third-party movies.
They cover byte-for-byte real HTTP streaming while the API remains responsive,
range requests, transfer completion and truncation,
size limits, unsafe redirects and DNS, queue capacity, cancellation, retry,
restart recovery, source-URL redaction, file retrieval, and browser boundaries.
Catalog tests also cover guest-token refresh, persisted titles after reload,
movie/series detection, valid episodes, whole-season queue capacity, and subtitles.

Manual verification on Python 3.14 included Chrome desktop/mobile searches,
movie quality selection, series season 2 episode 7, and subtitle controls. A real
Sintel 360p download completed at 58,502,555 bytes; `ffprobe` confirmed H.264 video,
AAC audio, 640×360 resolution, and 889 seconds of duration. Completed file retrieval
returned HTTP 206 for a 256-byte range request. These live checks depend on the
external provider and are separate from the deterministic regression suite.

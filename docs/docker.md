# Running with Docker

The [README quick start](../README.md#quick-start-5-minutes) covers the recommended way to run the sandbox: **Docker Compose**. This page covers:

1. **[Docker Compose details](#docker-compose)**: options, ports and environment variables
2. **[Build and `docker run`](#build-and-docker-run)**: start the container without Compose
3. **[The pre-built Docker Hub image](#the-pre-built-docker-hub-image)**: an older release without ModSecurity

> **Using Podman instead of Docker?** See [podman.md](podman.md).

---

## Prerequisites

1. **Docker Desktop.** Download it from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/), install it and start it. Check it works:
   ```bash
   docker --version
   docker ps
   ```
   Both commands should run without errors. A Docker Hub account isn't required.
2. **Git.** Check with `git --version`.
   - **Mac:** macOS offers to install it the first time you run `git`
   - **Windows:** [git-scm.com/downloads](https://git-scm.com/downloads)
   - **Linux:** `sudo apt install git` or `sudo dnf install git`
3. **The code:**
   ```bash
   git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
   cd aem-dispatcher-filter-testing
   ```

---

## Docker Compose

```bash
docker compose up --build
```

- The image is **built from this checkout** (`pull_policy: build` in `docker-compose.yml`), so you always run the code you have. The first build takes a few minutes; later ones reuse the cache and take seconds.
- Add `-d` to run in the background: `docker compose up --build -d`. Follow the output with `docker compose logs -f`.
- Stop with `Ctrl+C` (foreground) or `docker compose down`.

Then open **http://127.0.0.1:59173**. The control panel installs the dispatcher module the first time you open it (see the [README](../README.md#quick-start-5-minutes)).

### What Compose sets up

| Setting | Value | Why |
|---|---|---|
| Platform | `linux/amd64` | The Adobe dispatcher module for Rocky Linux 8 is x86_64. Runs fine on Apple Silicon. |
| Port `80` | dispatcher | Send test traffic to `http://localhost` |
| Port `127.0.0.1:59173` | control panel | Bound to your machine only (not your network) |
| `./filters/` | `/etc/httpd/conf.dispatcher.d/filters/` | Dispatcher filter files and panel settings |
| `./modsecurity/` | `/etc/httpd/modsecurity.d/rules/` | Your ModSecurity rule set |
| `./tests/` | `/usr/local/share/tests/` | Saved test lists |
| `./logs/` | `/var/log/httpd/` | All log files |

### Environment variables

Copy `.env.example` to `.env` and edit it to override the defaults:

| Variable | Default | Description |
|---|---|---|
| `CONTROL_PORT` | `59173` | Port for the control panel. Change it if 59173 is taken, then open `http://127.0.0.1:<port>`. |
| `TEST_URL_BASE` | `http://127.0.0.1` | Base URL the panel sends test requests to (inside the container) |

To change the dispatcher port (for example if port 80 is taken), edit `"80:80"` in `docker-compose.yml` to `"8080:80"` and use `http://localhost:8080`.

---

## Build and `docker run`

Use this if you don't want Compose.

### Step 1: Build the image

```bash
docker build --platform linux/amd64 -t aem-dispatcher-sandbox .
```

### Step 2: Run the container

From the repository folder (Mac / Linux / WSL):

```bash
docker run --rm --platform linux/amd64 \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v "$(pwd)/filters":/etc/httpd/conf.dispatcher.d/filters/ \
  -v "$(pwd)/modsecurity":/etc/httpd/modsecurity.d/rules/ \
  -v "$(pwd)/tests":/usr/local/share/tests/ \
  -v "$(pwd)/logs":/var/log/httpd/ \
  aem-dispatcher-sandbox
```

On Windows PowerShell, replace `$(pwd)` with `${PWD}` and the trailing `\` with a backtick (`` ` ``).

| Flag | What it does |
|---|---|
| `--rm` | Removes the container when it stops. Your files in the mounted folders are kept. |
| `-p 80:80` | Dispatcher on `http://localhost` |
| `-p 127.0.0.1:59173:59173` | Control panel on `http://127.0.0.1:59173`, reachable only from your machine |
| `-e CONTROL_PORT=59173` | Port the control panel listens on inside the container (keep it equal to the published port) |
| `-v …/filters`, `-v …/modsecurity`, `-v …/tests`, `-v …/logs` | Share your filters, ModSecurity rules, saved tests and logs with the container |

### Step 3: Open the control panel

Open `http://127.0.0.1:59173`. The dispatcher module installs automatically on first open.

Stop the container with `Ctrl+C`, or `docker stop <container-id>` (see `docker ps`).

---

## The pre-built Docker Hub image

[`pryor/aem-dispatcher-filter-testing:rockylinux8v2`](https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing) is an earlier release published to Docker Hub. It supports **dispatcher filters only, without ModSecurity**. For ModSecurity testing, build from source as shown above.

```bash
docker run --rm --platform linux/amd64 \
  -p 80:80 -p 127.0.0.1:59173:59173 -e CONTROL_PORT=59173 \
  -v "$(pwd)/filters":/etc/httpd/conf.dispatcher.d/filters/ \
  -v "$(pwd)/logs":/var/log/httpd/ \
  pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

---

## Troubleshooting

**`port is already allocated` / `address already in use`**
Port 80 or 59173 is in use (`docker ps` shows other containers). Stop the other program, or publish different ports: change `-p 80:80` to `-p 8080:80`, and for the panel change both `-p 127.0.0.1:59173:59173` and `-e CONTROL_PORT=59173` to the same free port.

**The control panel loads but the dispatcher doesn't respond on port 80**
The dispatcher module isn't installed yet. Install it from the window the panel shows, or from **Sandbox Controls → Dispatcher module version**.

**`Cannot load modules/dispatcher/mod_dispatcher.so`**
Don't mount `./dispatcher/` unless it holds a valid Linux x86_64 `mod_dispatcher.so`. See [`dispatcher/README.md`](../dispatcher/README.md).

**Changes to filter files don't take effect**
Use **Filters → Save & Restart**, or **Sandbox Controls → Restart dispatcher**.

**ModSecurity changes don't take effect**
The change failed the `httpd -t` check. Look at the ModSecurity tab, or run `docker compose logs` and look for `httpd config test FAILED`.

---

← [Back to main README](../README.md)

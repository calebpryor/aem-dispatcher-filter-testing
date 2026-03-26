# Docker Installation Guide

This guide covers three ways to run the AEM Dispatcher Filter Sandbox with Docker:

1. **[Docker Compose](#docker-compose)** — recommended for most users; pulls the pre-built image and manages everything for you
2. **[Pull and Run](#pull-and-run)** — pull the pre-built image from Docker Hub and start it with a `docker run` command
3. **[Build and Run](#build-and-run)** — build the image yourself from the source code, then start it with `docker run`

All three methods end up with the same running container. The difference is only in how you get the image.

> **Using Podman instead of Docker?** See [podman.md](podman.md).

---

## Prerequisites

### Install Docker

1. Create a free account at [hub.docker.com](https://hub.docker.com/signup) — you need this to pull images
2. Download and install **Docker Desktop** from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
3. Run through the installer, launch Docker Desktop, and sign in with your Docker Hub account
4. Verify it's working by opening a terminal and running:

```bash
docker --version
```

You should see a version number like `Docker version 26.x.x`.

### Install Git

Git is needed to clone this repository.

- **Mac:** Git is included with Xcode Command Line Tools. Run `git --version` and macOS will prompt you to install it if missing.
- **Windows:** Download from [git-scm.com](https://git-scm.com/downloads)
- **Linux:** Install via your package manager, e.g. `sudo apt install git` or `sudo dnf install git`

---

## Docker Compose

Docker Compose is the easiest method. One command pulls the image (or builds it) and starts the container with the correct ports and volume mounts already configured.

### Step 1 — Clone the repository

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

### Step 2 — Start the container

**Using the pre-built image from Docker Hub (fastest):**

```bash
docker compose up
```

This pulls `pryor/aem-dispatcher-filter-testing:rockylinux8v2` from Docker Hub and starts it. You only download the image once; subsequent runs use the cached copy.

**Or, build the image locally from source:**

```bash
docker compose up --build
```

This reads the `Dockerfile` in the repository and builds the image on your machine before starting. Use this if you want to verify what's in the image, or if you've modified the `Dockerfile`.

### Step 3 — Open the control panel

Once the container is running you will see log output in your terminal. Open your browser and go to:

```
http://127.0.0.1:59173
```

You should see the **Dispatcher Sandbox control panel**.

### Step 4 — Install the dispatcher module

The Apache module (`mod_dispatcher.so`) is not included in the image. You must download it once through the control panel:

1. Click the **Module Version** tab (or press `Ctrl+Shift+2`)
2. Select a version from the dropdown (use the latest unless you need a specific version)
3. Click **Download & switch module**
4. Wait for the spinner to finish — Apache restarts automatically

After this, the dispatcher is live at **http://localhost**.

### Stopping the container

Press `Ctrl+C` in the terminal where Compose is running, or from another terminal:

```bash
docker compose down
```

Your filter files in `./filters/` and logs in `./logs/` are preserved on your machine between runs.

### Changing the control panel port

If port `59173` is already in use on your machine:

```bash
cp .env.example .env
# Edit .env and change CONTROL_PORT to a free port, e.g. 49821
docker compose up
```

### Environment variables

Copy `.env.example` to `.env` to override defaults:

| Variable | Default | Description |
|---|---|---|
| `CONTROL_PORT` | `59173` | Port for the browser control panel |
| `TEST_URL_BASE` | `http://127.0.0.1` | Base URL used when running path tests |

---

## Pull and Run

Use this method if you want to start the container without Compose and without building anything locally.

### Step 1 — Pull the image

```bash
docker pull pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

This downloads the pre-built image from Docker Hub to your machine. It only needs to happen once.

### Step 2 — Clone the repo (for filter files and logs)

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

You need the local `filters/` and `logs/` directories to exist so the container has somewhere to read your filter rules from and write logs to.

### Step 3 — Run the container

Replace `/FULL/PATH/TO/aem-dispatcher-filter-testing` with the actual path to where you cloned the repo:

```bash
docker run \
  --rm \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v /FULL/PATH/TO/aem-dispatcher-filter-testing/filters/:/etc/httpd/conf.dispatcher.d/filters/ \
  -v /FULL/PATH/TO/aem-dispatcher-filter-testing/logs/:/var/log/httpd/ \
  pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

**What each flag does:**

| Flag | What it does |
|---|---|
| `--rm` | Removes the container automatically when you stop it |
| `-p 80:80` | Maps port 80 on your machine to port 80 in the container (the dispatcher) |
| `-p 127.0.0.1:59173:59173` | Maps port 59173 on localhost to the control panel (loopback-only for safety) |
| `-e CONTROL_PORT=59173` | Tells the container which port the control panel should listen on |
| `-v .../filters:/etc/httpd/conf.dispatcher.d/filters/` | Mounts your local filter files into the container |
| `-v .../logs:/var/log/httpd/` | Mounts the log directory so logs are written to your machine |

### Step 4 — Install the dispatcher module and open the control panel

Same as the Compose method: open `http://127.0.0.1:59173`, go to the **Module Version** tab, and download the module.

---

## Build and Run

Use this method if you want to build the image from source — for example, to audit the `Dockerfile`, make changes to the image, or avoid relying on a pre-built image you didn't create.

### Step 1 — Clone the repository

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

### Step 2 — Build the image

```bash
docker build -t pryor/aem-dispatcher-filter-testing:rockylinux8v2 .
```

This reads the `Dockerfile` in the current directory and creates a local image tagged `pryor/aem-dispatcher-filter-testing:rockylinux8v2`. Building takes a few minutes the first time as it installs packages inside the image.

If you're on Apple Silicon (M1/M2/M3 Mac) and want to explicitly build for x86_64 (recommended, to match the dispatcher module architecture):

```bash
docker buildx build --platform linux/amd64 -t pryor/aem-dispatcher-filter-testing:rockylinux8v2 .
```

### Step 3 — Run the container

```bash
docker run \
  --rm \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v "$(pwd)/filters":/etc/httpd/conf.dispatcher.d/filters/ \
  -v "$(pwd)/logs":/var/log/httpd/ \
  pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

Using `$(pwd)` automatically fills in the full path to the current directory (works on Mac/Linux). On Windows with PowerShell, replace `$(pwd)` with `${PWD}`.

### Step 4 — Install the dispatcher module and open the control panel

Open `http://127.0.0.1:59173`, go to the **Module Version** tab, and download the module.

---

## Troubleshooting

**`port is already allocated` or `address already in use`**
Something else on your machine is using port 80 or 59173. For port 80, change `-p 80:80` to `-p 8080:80` in your run command and access the dispatcher at `http://localhost:8080`. For port 59173, change the `-p 127.0.0.1:59173:59173` flag and the `-e CONTROL_PORT=` value to a free port.

**The control panel loads but the dispatcher doesn't respond on port 80**
The dispatcher module hasn't been installed yet. Open `http://127.0.0.1:59173` and install it from the Module Version tab.

**`Cannot load modules/dispatcher/mod_dispatcher.so`**
You may have an old empty file in `./dispatcher/`. The default Compose and `docker run` commands above do **not** mount `./dispatcher/` — if you added a mount for it, remove it unless you have a valid Linux `.so` file there. See [`dispatcher/README.md`](../dispatcher/README.md).

**The image takes a long time to pull**
The image is about 500 MB. This is normal for the first pull. Docker caches it so subsequent starts are instant.

**Filter changes don't take effect**
Save your filter file and restart the dispatcher. In the control panel, go to **Server Controls → Restart dispatcher**, or use **Filters → Save & Restart**.

---

← [Back to main README](../README.md)

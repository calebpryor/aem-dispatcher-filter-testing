# Podman Installation Guide

Podman is a Docker-compatible container engine that runs containers without requiring a system daemon. It is available on Linux, Mac, and Windows, and can run this project with no changes to the image or the `docker-compose.yml` file.

This guide covers two methods:

1. **[Podman Compose](#podman-compose)** — recommended; uses the same `docker-compose.yml` that Docker uses
2. **[Podman Run](#podman-run)** — start the container directly with a `podman run` command

> **Using Docker instead of Podman?** See [docker.md](docker.md).

---

## Prerequisites

### Install Podman

**Option A — Podman Desktop (easiest for Mac and Windows)**

Download and install from [podman-desktop.io/downloads](https://podman-desktop.io/downloads). Run through the installer, then launch Podman Desktop. It manages a virtual machine for you automatically.

**Option B — Podman CLI only**

- **Mac:** `brew install podman` then `podman machine init && podman machine start`
- **Fedora/RHEL/CentOS:** `sudo dnf install podman`
- **Ubuntu/Debian:** `sudo apt install podman`
- **Windows:** Use [Podman Desktop](https://podman-desktop.io/downloads) or WSL2

Verify the installation:

```bash
podman --version
```

### Install `podman-compose` (for the Compose method)

If you want to use the Compose method, install `podman-compose`:

```bash
pip3 install podman-compose
```

Or on Fedora/RHEL:

```bash
sudo dnf install podman-compose
```

Alternatively, enable **Docker compatibility mode** in Podman Desktop settings and use the `docker compose` command — it will route through Podman automatically.

### Install Git

- **Mac:** Run `git --version` — macOS will prompt you to install it if missing
- **Fedora/RHEL:** `sudo dnf install git`
- **Ubuntu/Debian:** `sudo apt install git`
- **Windows:** Download from [git-scm.com](https://git-scm.com/downloads)

---

## Podman Compose

### Step 1 — Clone the repository

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

### Step 2 — Start the container

```bash
podman compose up
```

Or, if you're using Docker compatibility mode in Podman Desktop:

```bash
docker compose up
```

Podman reads the same `docker-compose.yml` file that Docker uses. The image (`pryor/aem-dispatcher-filter-testing:rockylinux8v2`) is pulled from Docker Hub automatically on first run.

To build the image locally from source instead of pulling it:

```bash
podman compose up --build
```

### Step 3 — Open the control panel

Once the container is running, open your browser and go to:

```
http://127.0.0.1:59173
```

### Step 4 — Install the dispatcher module

1. Click the **Module Version** tab (or press `Ctrl+Shift+2`)
2. Select a version and click **Download & switch module**
3. Wait for the spinner — Apache restarts automatically

After this, the dispatcher is live at **http://localhost**.

### Stopping the container

```bash
podman compose down
```

Your filter files and logs are preserved in `./filters/` and `./logs/` on your machine.

### Changing the control panel port

```bash
cp .env.example .env
# Edit .env and set CONTROL_PORT to a free port, e.g. 49821
podman compose up
```

---

## Podman Run

Use this to start the container directly without Compose.

### Step 1 — Pull the image

```bash
podman pull docker.io/pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

> Note: Podman requires the full registry prefix (`docker.io/`) when pulling from Docker Hub.

### Step 2 — Clone the repo (for filter files and logs)

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

### Step 3 — Run the container

Replace `/FULL/PATH/TO/aem-dispatcher-filter-testing` with the actual path to where you cloned the repo:

```bash
podman run \
  --rm \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v /FULL/PATH/TO/aem-dispatcher-filter-testing/filters/:/etc/httpd/conf.dispatcher.d/filters/:z \
  -v /FULL/PATH/TO/aem-dispatcher-filter-testing/logs/:/var/log/httpd/:z \
  docker.io/pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

> The `:z` suffix on the volume mounts is a **SELinux** label flag. It is harmless on systems without SELinux and required on Fedora, RHEL, and CentOS to allow the container to read/write the mounted directories. See [Platform-Specific Notes](#platform-specific-notes) below.

### Step 4 — Install the dispatcher module and open the control panel

Open `http://127.0.0.1:59173`, go to the **Module Version** tab, and download the module.

---

## Platform-Specific Notes

### Linux — rootless Podman and port 80

On Linux, Podman runs **rootless** by default, which means binding to ports below 1024 (like port 80) may be blocked by the kernel.

**Option A — Change the published port**

Replace `-p 80:80` with a high port:

```bash
-p 8080:80
```

Then access the dispatcher at `http://localhost:8080`.

**Option B — Allow unprivileged low-port binding (system-wide)**

```bash
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
```

To make this permanent, add it to `/etc/sysctl.d/99-podman.conf`.

### Linux — SELinux (Fedora, RHEL, CentOS)

If Podman denies access to your mounted `filters/` or `logs/` directories, SELinux is blocking it.

**Fix for `podman run`:** Append `:z` to each `-v` flag (as shown in the run command above).

**Fix for Compose:** Add `:z` to each volume in `docker-compose.yml`:

```yaml
volumes:
  - ./filters/:/etc/httpd/conf.dispatcher.d/filters/:z
  - ./logs/:/var/log/httpd/:z
```

### Mac — Docker compatibility mode

If you have scripts or muscle memory that type `docker` instead of `podman`, enable **Docker compatibility** in Podman Desktop:

1. Open Podman Desktop
2. Go to **Settings → Preferences**
3. Enable **Docker Compatibility**

This creates a Docker socket so `docker` commands work with Podman.

### Windows

Use **Podman Desktop** on Windows. It manages a WSL2-based virtual machine for you. Once installed, use the terminal inside Podman Desktop or your WSL2 shell.

---

## Building from Source with Podman

If you prefer to build the image yourself rather than pulling it:

```bash
podman build -t pryor/aem-dispatcher-filter-testing:rockylinux8v2 .
```

For Apple Silicon Macs or if you want to explicitly target x86_64:

```bash
podman build --platform linux/amd64 -t pryor/aem-dispatcher-filter-testing:rockylinux8v2 .
```

Then run with the image you just built:

```bash
podman run \
  --rm \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v "$(pwd)/filters":/etc/httpd/conf.dispatcher.d/filters/:z \
  -v "$(pwd)/logs":/var/log/httpd/:z \
  pryor/aem-dispatcher-filter-testing:rockylinux8v2
```

---

## Troubleshooting

**`Error: short-name resolution` when pulling the image**
Add the full registry prefix: `docker.io/pryor/aem-dispatcher-filter-testing:rockylinux8v2`

**Port 80 access denied on Linux**
See [Linux — rootless Podman and port 80](#linux--rootless-podman-and-port-80) above.

**`permission denied` on volume mounts (Fedora/RHEL/CentOS)**
See [Linux — SELinux](#linux--selinux-fedora-rhel-centos) above. Add `:z` to your `-v` mounts.

**The control panel loads but Apache doesn't respond on port 80**
The dispatcher module hasn't been installed yet. Open `http://127.0.0.1:59173` and install it from the Module Version tab.

**`podman compose` command not found**
Install `podman-compose`: `pip3 install podman-compose`, or enable Docker compatibility in Podman Desktop and use `docker compose` instead.

---

← [Back to main README](../README.md)

# Running with Podman

Podman is a Docker-compatible container engine that doesn't need a background daemon. It runs this project with the same `Dockerfile` and `docker-compose.yml`.

This page covers:

1. **[Podman Compose](#podman-compose)** (recommended)
2. **[Build and `podman run`](#build-and-podman-run)**
3. **[Platform notes](#platform-notes)**: Linux ports, SELinux, Mac, Windows

> **Using Docker instead?** Follow the [README quick start](../README.md#quick-start-5-minutes) or [docker.md](docker.md).

---

## Prerequisites

### Install Podman

**Option A: Podman Desktop (easiest on Mac and Windows).** Download it from [podman-desktop.io/downloads](https://podman-desktop.io/downloads), install it and start it. On first start it offers to create a **Podman machine** (a small Linux VM). Accept.

**Option B: command line only**

- **Mac:** `brew install podman`, then `podman machine init && podman machine start`
- **Fedora / RHEL:** `sudo dnf install podman`
- **Ubuntu / Debian:** `sudo apt install podman`
- **Windows:** use Podman Desktop (it runs on WSL2)

Check that it works:

```bash
podman --version
podman ps
```

### Install a Compose provider

`podman compose` needs a Compose program behind it. Use one of these:

- `pip3 install podman-compose` (or `sudo dnf install podman-compose` on Fedora / RHEL)
- **Podman Desktop → Settings → Resources → Compose → Setup**, which installs `docker-compose` for Podman

### Get the code

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

---

## Podman Compose

```bash
podman compose up --build
```

The image is built from this checkout. The first build takes a few minutes. When the output shows `Control panel listening on 0.0.0.0:59173`, open **http://127.0.0.1:59173**. The panel installs the dispatcher module the first time you open it. Then follow the walkthroughs in the [README](../README.md#walkthrough-test-dispatcher-filters).

Stop with `Ctrl+C` or `podman compose down`. Change the control panel port with `cp .env.example .env` and edit `CONTROL_PORT`.

> On **Linux**, see [rootless Podman and port 80](#linux-rootless-podman-and-port-80) and [SELinux](#linux-selinux-fedora-rhel-centos) before starting.

---

## Build and `podman run`

```bash
podman build --platform linux/amd64 -t aem-dispatcher-sandbox .

podman run --rm --platform linux/amd64 \
  -p 80:80 \
  -p 127.0.0.1:59173:59173 \
  -e CONTROL_PORT=59173 \
  -v "$(pwd)/filters":/etc/httpd/conf.dispatcher.d/filters/:z \
  -v "$(pwd)/modsecurity":/etc/httpd/modsecurity.d/rules/:z \
  -v "$(pwd)/tests":/usr/local/share/tests/:z \
  -v "$(pwd)/logs":/var/log/httpd/:z \
  localhost/aem-dispatcher-sandbox
```

The `:z` at the end of each `-v` is an SELinux label. It's required on Fedora / RHEL / CentOS and harmless elsewhere.

Then open `http://127.0.0.1:59173`.

---

## Platform notes

### Linux: rootless Podman and port 80

Rootless Podman can't publish ports below 1024 by default. Either:

- **Use a high port.** Change `-p 80:80` to `-p 8080:80` (or `"8080:80"` in `docker-compose.yml`) and use `http://localhost:8080`, **or**
- **Allow low ports.** Run `sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80`. To make it permanent, add that setting to `/etc/sysctl.d/99-podman.conf`.

### Linux: SELinux (Fedora, RHEL, CentOS)

If the container gets `permission denied` on the mounted folders, add `:z` to every volume:

- **`podman run`:** already shown above
- **Compose:** edit `docker-compose.yml`:

```yaml
volumes:
  - ./filters/:/etc/httpd/conf.dispatcher.d/filters/:z
  - ./logs/:/var/log/httpd/:z
  - ./modsecurity/:/etc/httpd/modsecurity.d/rules/:z
  - ./tests/:/usr/local/share/tests/:z
```

### Mac: Apple Silicon

The image runs as `linux/amd64` (x86_64) on purpose. The Adobe dispatcher module for Rocky Linux 8 is x86_64-only. Podman uses emulation automatically, so nothing extra is needed.

### Mac / Windows: Docker compatibility

To type `docker` instead of `podman`, enable **Docker Compatibility** in **Podman Desktop → Settings → Preferences**. After that, `docker compose up --build` works as in the README.

### Windows

Use **Podman Desktop**, which manages a WSL2 VM. Run the commands from the Podman Desktop terminal or your WSL2 shell.

---

## Troubleshooting

**`podman compose` says no compose provider was found**
Install one; see [Install a Compose provider](#install-a-compose-provider).

**`Error: short-name resolution`**
Use the full image name, for example `docker.io/library/rockylinux:8`, or add `docker.io` to `unqualified-search-registries` in `/etc/containers/registries.conf`.

**Port 80 access denied on Linux**
See [rootless Podman and port 80](#linux-rootless-podman-and-port-80).

**`permission denied` on the mounted folders**
See [SELinux](#linux-selinux-fedora-rhel-centos).

**The control panel loads but the dispatcher doesn't respond on port 80**
The dispatcher module isn't installed yet. Install it from the window the panel shows, or from **Sandbox Controls → Dispatcher module version**.

---

← [Back to main README](../README.md)

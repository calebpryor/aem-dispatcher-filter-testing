# AEM Dispatcher Filter Sandbox

A local sandbox for writing and testing [Adobe Experience Manager](https://business.adobe.com/products/experience-manager/adobe-experience-manager.html) Dispatcher filter rules — no AEM licence or cloud account required.

> **Image on Docker Hub:** [pryor/aem-dispatcher-filter-testing](https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing)

---

## What is this?

Adobe Experience Manager (AEM) is a content management platform that is almost always fronted by the **AEM Dispatcher** — an Apache web server module that acts as a proxy, cache, and access-control layer between the internet and your AEM author/publish instances.

Dispatcher **filter rules** control which HTTP requests are allowed through and which are blocked. Getting them right matters for security and performance, but testing them normally requires a full AEM environment.

This project gives you a self-contained sandbox:

- A **fake AEM renderer** (a simple Apache vhost on port 4503) that acts as the backend
- A real **Apache + mod_dispatcher.so** setup so your filter rules are evaluated exactly as they would be in production
- A **browser-based control panel** for managing filter rules, running tests, viewing live logs, and switching dispatcher module versions

You can spin it up in a few minutes, write rules, run path tests, and tear it down when you're done.

---

## Demo

**Starting the container and installing the dispatcher module:**

![Starting Container](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/v.2/dispatcher-filter-testing-compose.gif)

**Using the control panel to test filter rules:**

![Browser Testing Filters](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/v.2/dispatcher-filter-testing-examples.gif)

---

## What do you need?

1. **Docker or Podman** installed on your machine (see the guides below)
2. **Git** to clone this repository
3. A terminal (Terminal.app on Mac, PowerShell or WSL on Windows, any shell on Linux)

You do **not** need an Adobe account to use this sandbox. The dispatcher module (`mod_dispatcher.so`) is downloaded from Adobe's public CDN through the control panel after the container starts.

---

## Quick Start (recommended)

The fastest path is Docker Compose. This pulls the pre-built image and starts everything in one command.

**1. Clone this repo**

```bash
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

**2. Start the container**

```bash
docker compose up
```

**3. Open the control panel and install the dispatcher module**

Open **[http://127.0.0.1:59173](http://127.0.0.1:59173)** in your browser.

On the **Module Version** tab, select a version and click **Download & switch module**. Apache waits for this step — the dispatcher will not start until the module file is downloaded.

That's it. Once the module is installed, your dispatcher is live on **[http://localhost](http://localhost)**.

---

## Installation Guides

Choose the guide that matches your setup:

| Method | Guide |
|---|---|
| **Docker** — Compose (recommended) | [docs/docker.md#docker-compose](docs/docker.md#docker-compose) |
| **Docker** — Pull pre-built image + `docker run` | [docs/docker.md#pull-and-run](docs/docker.md#pull-and-run) |
| **Docker** — Build from source + `docker run` | [docs/docker.md#build-and-run](docs/docker.md#build-and-run) |
| **Podman** — Compose | [docs/podman.md#podman-compose](docs/podman.md#podman-compose) |
| **Podman** — `podman run` | [docs/podman.md#podman-run](docs/podman.md#podman-run) |

---

## After Starting

### Install the dispatcher module

The `mod_dispatcher.so` Apache module is **not** bundled in the image. After the container starts:

1. Open the control panel at **http://127.0.0.1:59173**
2. Go to the **Module Version** tab
3. Select a version from the dropdown and click **Download & switch module**
4. Wait for the download and restart to complete (a spinner shows progress)

Apache will not respond on port 80 until this step is done — this is by design so the module file is always the correct architecture for the container.

### Control panel tabs

| Tab | What it does |
|---|---|
| **Server Controls** | View service health, restart Apache |
| **Module Version** | Download and switch `mod_dispatcher.so` versions |
| **Filters** | View active rules, edit `002_web_filters.any`, set default policy (deny-all / allow-all) |
| **Testing** | Run HTTP requests against the dispatcher and see which rule allowed or blocked each one |
| **Logs** | Live-streaming log viewer for all httpd and dispatcher logs |

**Keyboard shortcut:** `Ctrl+Shift+1` through `Ctrl+Shift+5` jumps between tabs.

---

## Filter Files

Filter files live in the `filters/` directory in this repo, which is bind-mounted into the container at `/etc/httpd/conf.dispatcher.d/filters/`. Any `.any` file in that folder is picked up automatically.

Name files with a numeric prefix to control load order:

```
filters/
  001_baseline.any      ← loaded first
  002_web_filters.any   ← loaded second (editable from the control panel)
  010_project.any       ← loaded third
```

Rules are evaluated **last-match-wins** — the last rule that matches a request determines whether it is allowed or blocked.

See [`filters/README.md`](filters/README.md) for more detail.

---

## Default Policy (Sandbox Mode)

The **Filters tab** in the control panel has a **Default Policy** toggle:

- **Deny all (test allow rules)** — everything is blocked by default; write `allow` rules for paths that should pass through. This is the production-safe starting point.
- **Allow all (test deny rules)** — everything passes by default; write `deny` rules for paths that should be blocked. Useful when auditing what you need to lock down.

Switching modes restarts the dispatcher automatically.

---

## Logs

Log files are written to the `logs/` directory (bind-mounted from the container):

| File | Contents |
|---|---|
| `dispatcher.log` | Full dispatcher trace log |
| `filter-test.log` | Filter decisions only (auto-extracted) |
| `access_log` | Apache access log |
| `error_log` | Apache error log |
| `renderer_access_log` | Renderer (fake AEM) access log |
| `renderer_error_log` | Renderer error log |

All logs are viewable live in the **Logs tab** of the control panel.

---

## Troubleshooting

**Apache won't start / dispatcher not responding on port 80**
The module has not been installed yet. Open the control panel at `http://127.0.0.1:59173` and install it from the Module Version tab.

**Control panel not reachable (`connection refused` on 59173)**
Check that the container started: `docker compose ps` and `docker compose logs`.
If the port is already in use on your machine, copy `.env.example` to `.env`, change `CONTROL_PORT` to a free port (e.g. `49821`), and restart: `docker compose up`.

**Port 80 already in use**
Another process is using port 80. Stop it, or change the published port in `docker-compose.yml` from `"80:80"` to something like `"8080:80"`, then access the dispatcher at `http://localhost:8080`.

**`GLIBC` errors or module fails to load**
The image is pinned to `linux/amd64` (x86_64) in `docker-compose.yml` because the arm64 dispatcher build requires a newer glibc than Rocky Linux 8 provides. This is expected and handled automatically when you use the provided `docker-compose.yml`.

**Filters not updating after saving**
Save your filter file and click **Save & Restart** in the Filters tab, or manually restart from Server Controls. The dispatcher re-reads filter files on restart.

---

## Reference

- [Dispatcher filter configuration docs (Adobe)](https://docs.adobe.com/content/help/en/experience-manager-dispatcher/using/configuring/dispatcher-configuration.html#configuring-access-to-content-filter)
- [`filters/README.md`](filters/README.md) — filter file conventions
- [`dispatcher/README.md`](dispatcher/README.md) — supplying your own `mod_dispatcher.so`
- [Docker Hub image](https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing)

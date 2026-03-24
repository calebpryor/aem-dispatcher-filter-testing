# Adobe Experience Manager Dispatcher filter testing Docker image
This image is located in docker hub here:
https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing

This repo is the Dockerfile source and dependent files to make this work.
Instructions are here and in docker hub for convenience.

# What is this?
Adobe Experience Manager is an Adobe product that uses Apache Sling.  Apache Sling is powerful and weird.
With each deployment of AEM it's normally fronted with a different webserver that uses a module written specifically for AEM.  It's an intelligent proxy / cache / access control web tier.

Writing filters for the dispatcher can be challenging and there isn't an easy sandbox for people to sharpen their skills with.  This docker image stands up a fake backend renderer to act as AEM and an Apache Webserver that uses the dispatcher handler .so file and base configuration farm to make it work.

This way you can stand up a quick box to create a new filter rule for and get it to work and tear it down quickly.

# What is the point?
One challenge is writing good dispatcher filter rules from the documentation listed here:
https://docs.adobe.com/content/help/en/experience-manager-dispatcher/using/configuring/dispatcher-configuration.html#configuring-access-to-content-filter

# Demo

![Starting Container](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/master/dispatcher-filter-testing-compose.gif)

![Browser Testing Filters](https://raw.githubusercontent.com/calebpryor/aem-dispatcher-filter-testing/master/dispatcher-filter-testing-examples.gif)

# What do I need?

## Docker

Create an account on [hub.docker.com](https://hub.docker.com/signup) you'll need it for pulling down public docker images.

Use your favorite installation to get Docker running on your machine.

The easiest option is `Docker Desktop` and you can get the installation media from [here](https://www.docker.com/products/docker-desktop/)

Run through the standard installation wizard and login to the client with your docker account.

## Clone this repo

```
git clone https://github.com/calebpryor/aem-dispatcher-filter-testing.git
cd aem-dispatcher-filter-testing
```

## Create your own filter files

Then create any filters files you want with a .any extension with your filter rules you want to test.
Drop those files in the filters directory.
This file will get mapped to your workstation so you can make changes and re-run your docker image and it will pick up the changes.

## Get and run the container

There are different methods to use: Docker or Podman, `compose` or plain `run`.

The Compose file is `docker-compose.yml` (only one file — having both `compose.yaml` and `docker-compose.yml` makes Compose warn and pick one arbitrarily).

### docker compose (Easier)

From a clone of this repo, build and run so you get the current Dockerfile (including the control UI on **`CONTROL_PORT`, default 59173**):

```
docker compose up --build
```

Optional: copy `.env.example` to `.env` and set `CONTROL_PORT` to any high, unused port if your Mac, VPN, or corporate stack blocks localhost on specific numbers.

To use a pre-pulled image only (no local build), omit `--build` (Hub tags may be older than this repository).

### Dispatcher module (`mod_dispatcher.so`)

The Adobe module is **not** baked into the image and is **not** downloaded at container start. After `compose up`, open the **control UI** (`http://127.0.0.1` and your `CONTROL_PORT`, default **59173**) and use **Download & switch module** to fetch `mod_dispatcher.so`. Apache waits until that step completes.

**Do not** leave an empty or macOS / wrong-CPU file under `./dispatcher/` and mount it — that can make Apache fail to load the module. Default Compose mounts **filters** and **logs** only; see `dispatcher/README.md` if you need to supply your own Linux `mod_dispatcher.so`.

### Podman Desktop / Podman (compatible)

This project uses a standard Compose file and OCI builds, so you can use [Podman Desktop](https://podman-desktop.io/) or the Podman CLI the same way:

```
podman compose up
```

Build from source:

```
podman build -f Dockerfile -t pryor/aem-dispatcher-filter-testing:rockylinux8 .
```

Pull from Docker Hub (fully qualified name works everywhere):

```
podman pull docker.io/pryor/aem-dispatcher-filter-testing:rockylinux8
```

Run without Compose:

```
podman run -p 80:80 -p 127.0.0.1:59173:59173 -e CONTROL_PORT=59173 -v /DIR_YOU_CLONED_TO/filters/:/etc/httpd/conf.dispatcher.d/filters/ -v /DIR_YOU_CLONED_TO/logs/:/var/log/httpd/ docker.io/pryor/aem-dispatcher-filter-testing:rockylinux8
```

**Podman Desktop tips:** Enable **Docker compatibility** in Podman Desktop settings if you rely on a `docker` CLI alias to existing scripts. On **Linux rootless** Podman, binding host ports **below 1024** (e.g. `80:80`) may be blocked by your system; either allow unprivileged low ports for your user or change the published ports (for example map `9080:80` for the dispatcher and `127.0.0.1:59173:59173` for the control UI). If **SELinux** denies volume access on Fedora/RHEL-style hosts, append `:z` to each bind mount in the Compose file (e.g. `./filters/:/etc/httpd/conf.dispatcher.d/filters/:z`).

### docker pull or build

You can pull the published image from [hub.docker.com](https://hub.docker.com/r/pryor/aem-dispatcher-filter-testing):

```
docker pull pryor/aem-dispatcher-filter-testing:rockylinux8
```

Or if you want you can also build it yourself from the source in this repo so you can trust there isn't anything snuck in on the prebuild image.

Use this method if you want to make any alterations to the image as well.

```
docker build -t pryor/aem-dispatcher-filter-testing:rockylinux8 .
```

#### docker run

```
docker run -p 80:80 -p 127.0.0.1:59173:59173 -e CONTROL_PORT=59173 -v /DIR_YOU_CLONED_TO/filters/:/etc/httpd/conf.dispatcher.d/filters/ -v /DIR_YOU_CLONED_TO/logs/:/var/log/httpd/ pryor/aem-dispatcher-filter-testing:rockylinux8
```

Now you can tail the log files

```
tail -f logs/filter-test.log
```

As you visit your browser you'll see the relevant log entries for allows and denies for the filters

### Control UI (default `http://127.0.0.1:59173`)

The control panel is a small Python HTTP server inside the container (not Apache).

**Why 59173:** Low “well-known” ports (80, 8080, …) and even some high defaults (e.g. 55555) can already be in use locally. The default **`CONTROL_PORT=59173`** is an uncommon high port; override in `.env` if this one is also taken (`address already in use`). Compose publishes it on **loopback only** (`127.0.0.1:59173:59173`) so traffic stays on your machine.

**Platform mismatch:** If Compose warns that the image platform (e.g. `linux/arm64`) does not match the host (`linux/amd64`), run **`docker compose build --no-cache`** on **this** machine so the image matches your CPU, or uncomment **`platform: linux/amd64`** or **`platform: linux/arm64`** in `docker-compose.yml` to match your host.

**Outbound checks are misleading:** `curl portquiz.net:8080` only proves **outbound** internet access on port 8080. It says nothing about whether **Docker can publish** a port on `127.0.0.1` on your machine.

**If you still get connection reset / refused:**

1. Confirm the container is up: `docker compose ps` and `docker compose logs` (look for `Control panel listening on 0.0.0.0:59173`).
2. **`bind: address already in use`** — copy `.env.example` to `.env`, set `CONTROL_PORT=` to a free port (try `49821`), then `docker compose up --build` again.
3. Prefer **`http://127.0.0.1:…`** in the browser (avoids IPv6 / `localhost` oddities).
4. Rebuild so you are not on an old Hub image without the control server:

```
docker compose build --no-cache
docker compose up
```

Quick checks:

```
curl -sS http://127.0.0.1:59173/api/health
curl -I http://127.0.0.1:59173/
```

Use **`curl` GET** (or open the URL in a browser). `curl -I` sends **HEAD**, which is implemented; older images may only support GET.
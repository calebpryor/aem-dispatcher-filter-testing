## Optional vendor `mod_dispatcher.so`

Adobe’s closed-source module is **installed only from the control panel** inside the container (Download & switch module on `CONTROL_PORT`, default 59173). It is **not** downloaded when the container starts.

Until a valid Linux ELF `.so` for this CPU is present, both Apache processes (`dispatcher` on 80 and `renderer` on 4503) wait in a loop; the control UI stays available so you can run the download.

### Do not drop a broken file here by default

Mounting the whole directory `./dispatcher/` into the container can **override** the runtime path. If this folder was empty or contained a **macOS** / **wrong-arch** binary, Apache could fail with:

`Cannot load modules/dispatcher/mod_dispatcher.so ... No such file or directory`

**Default Compose does not mount this folder.**

### Using your own `mod_dispatcher.so`

1. Place a **Linux** `mod_dispatcher.so` built for **your container arch** (match `uname -m` inside the container: `x86_64` or `aarch64`).
2. Add **one** of these to `docker-compose.yml` under `volumes:`

**Single file (recommended):**

```yaml
- ./dispatcher/mod_dispatcher.so:/etc/httpd/modules/dispatcher/mod_dispatcher.so:ro
```

**Or** bind the directory (only if the file is valid for the VM’s CPU):

```yaml
- ./dispatcher/:/etc/httpd/modules/dispatcher/
```

3. `disp_module_valid.sh` checks the file with `file(1)`. If it is valid, `wait_httpd.sh` starts httpd without using the control-panel download.

### Legacy `docker run`

```text
docker run ... -v <FOLDER_WITH_mod_dispatcher.so>:/etc/httpd/modules/dispatcher/ ...
```

#!/usr/bin/env python3.9
"""
Local control plane for the dispatcher sandbox: version selection, httpd restart,
path-based URL smoke tests, and log browsing. Binds CONTROL_PORT (default 59173);
not intended for exposure beyond the developer machine.

Pages: / (control panel), /logs/view?name=… (log stream UI; SSE via /api/log-stream).
Tests POST JSON { good_paths, bad_paths } with request-URI
fragments; URLs are built with TEST_URL_BASE (default http://127.0.0.1).
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "59173"))
VERSIONS_FILE = Path(
    os.environ.get("DISPATCHER_VERSIONS_FILE", "/usr/local/share/dispatcher_versions.txt")
)
DOWNLOAD_SCRIPT = Path(
    os.environ.get("DOWNLOAD_DISPATCHER_SCRIPT", "/usr/local/bin/download_dispatcher.sh")
)
MODULE_VALID_SCRIPT = Path(
    os.environ.get("DISP_MODULE_VALID_SCRIPT", "/usr/local/bin/disp_module_valid.sh")
)
MODULE_VERSION_FILE = Path("/etc/httpd/modules/dispatcher/installed_version.txt")
DISPATCHER_LOG = Path("/var/log/httpd/dispatcher.log")
SANDBOX_POLICY_FILE = Path("/etc/httpd/conf.dispatcher.d/sandbox_policy.any")
_SANDBOX_DENY  = '# mode: deny_all\n/sandbox-default { /type "deny" /url "*" }\n'
_SANDBOX_ALLOW = '# mode: allow_all\n/sandbox-default { /type "allow" /url "*" }\n'
# Stored in the bind-mounted filters directory so it survives container restarts.
# Host-visible path: ./filters/.prefs.json
PREFS_FILE = Path("/etc/httpd/conf.dispatcher.d/filters/.prefs.json")
PREFS_HOST_DISPLAY = "./filters/.prefs.json"


def _read_prefs() -> Dict[str, Any]:
    try:
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pref(key: str, value: Any) -> None:
    prefs = _read_prefs()
    prefs[key] = value
    PREFS_FILE.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")


def _read_sandbox_mode() -> str:
    try:
        text = SANDBOX_POLICY_FILE.read_text(encoding="utf-8")
        if "mode: allow_all" in text:
            return "allow_all"
    except OSError:
        pass
    return "deny_all"
PANEL_HTML = Path(os.environ.get("CONTROL_PANEL_HTML", "/usr/local/share/control_panel.html"))
LOGS_VIEW_HTML = Path(os.environ.get("LOGS_VIEW_HTML", "/usr/local/share/logs_view.html"))
# Prepended to request paths from /api/test-urls (no trailing slash).
TEST_URL_BASE = os.environ.get("TEST_URL_BASE", "http://127.0.0.1").rstrip("/")
FILTERS_DIR = Path(
    os.environ.get("FILTERS_DIR", "/etc/httpd/conf.dispatcher.d/filters")
)
LOG_DIR = Path(os.environ.get("HTTPD_LOG_DIR", "/var/log/httpd"))
TESTS_DIR = Path(os.environ.get("TESTS_DIR", "/usr/local/share/tests"))
DEFAULT_TEST_PATHS_FILE = TESTS_DIR / "default_test_paths.json"
# Basenames only; paths are resolved strictly under LOG_DIR (no traversal).
ALLOWED_LOG_BASENAMES = frozenset(
    {
        "dispatcher.log",
        "filter-test.log",
        "error_log",
        "access_log",
        "renderer_error_log",
        "renderer_access_log",
    }
)
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
ALLOWED_PORTS = frozenset({80, 4503, 8080, 18080, 55555, 59173})


def _list_test_path_files() -> List[Dict[str, str]]:
    """Return all loadable test path JSON files from filters/ and tests/ directories.

    Each entry has 'key' (used as the load identifier, format "source:filename"),
    'label' (display name), and 'source' ("filters" or "tests").
    """
    entries: List[Dict[str, str]] = []
    if FILTERS_DIR.is_dir():
        for p in sorted(FILTERS_DIR.glob("*_test_paths.json")):
            if p.is_file():
                entries.append({"key": "filters:" + p.name, "label": p.name, "source": "filters"})
    if TESTS_DIR.is_dir():
        for p in sorted(TESTS_DIR.glob("*.json")):
            if p.is_file():
                entries.append({"key": "tests:" + p.name, "label": p.name + " (tests/)", "source": "tests"})
    return entries


def _read_test_path_file(source: str, filename: str) -> Dict[str, Any]:
    base_dir = TESTS_DIR if source == "tests" else FILTERS_DIR
    p = base_dir / filename
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"good_paths": [], "bad_paths": []}
    if not isinstance(data, dict):
        return {"good_paths": [], "bad_paths": []}
    out: Dict[str, Any] = {"good_paths": [], "bad_paths": []}
    for key in ("good_paths", "bad_paths"):
        val = data.get(key)
        if isinstance(val, list):
            out[key] = [str(x).strip() for x in val if isinstance(x, str) and str(x).strip()]
    return out


def _list_filter_files() -> List[str]:
    if not FILTERS_DIR.is_dir():
        return []
    out: List[str] = []
    for p in sorted(FILTERS_DIR.glob("*.any")):
        if p.is_file():
            out.append(p.name)
    return out


# Per-file cap when embedding filter text in API / export payloads (characters).
_MAX_FILTER_FILE_CHARS = 256_000


def _read_filter_rules() -> List[Dict[str, str]]:
    """Return each *.any file's basename and full text (same order as filter_files / $include glob)."""
    if not FILTERS_DIR.is_dir():
        return []
    out: List[Dict[str, str]] = []
    for p in sorted(FILTERS_DIR.glob("*.any")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if len(text) > _MAX_FILTER_FILE_CHARS:
            text = text[:_MAX_FILTER_FILE_CHARS] + "\n... [truncated] ..."
        out.append({"file": p.name, "content": text})
    return out


def _tail_log_file(basename: str, max_lines: int) -> Tuple[str, Optional[str]]:
    """
    Return (content, error_message). error_message set when the log cannot be read as a file.
    """
    if basename not in ALLOWED_LOG_BASENAMES:
        return "", "Unknown log name"
    path = LOG_DIR / basename
    try:
        (LOG_DIR / basename).resolve().relative_to(LOG_DIR.resolve())
    except ValueError:
        return "", "Invalid path"
    except OSError:
        return "", "Cannot resolve log directory"
    if not path.exists():
        return "", None
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            return (
                "",
                "This log is not a regular file (often Apache access/error are linked to "
                "container stdout/stderr). Use `docker compose logs` for those streams, or "
                "open dispatcher.log / filter-test.log here.",
            )
    except OSError as e:
        return "", str(e)
    max_bytes = min(512_000, max(st.st_size, 1))
    try:
        with path.open("rb") as f:
            if st.st_size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            raw = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return "", str(e)
    lines = raw.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines) + ("\n" if lines else ""), None


def _serve_log_stream(handler: BaseHTTPRequestHandler, qs: Dict[str, List[str]]) -> None:
    """Stream log lines over Server-Sent Events using `tail -F` (real-time follow)."""
    name = (qs.get("name") or [""])[0].strip()
    if name not in ALLOWED_LOG_BASENAMES:
        handler.send_error(400, "Unknown log name")
        return
    path = LOG_DIR / name
    try:
        path.resolve().relative_to(LOG_DIR.resolve())
    except ValueError:
        handler.send_error(400, "Invalid path")
        return
    except OSError:
        handler.send_error(500, "Cannot resolve log directory")
        return

    if path.exists():
        try:
            st = os.stat(path)
            if not stat.S_ISREG(st.st_mode):
                handler.send_response(200)
                handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
                handler.send_header("Cache-Control", "no-cache, no-transform")
                handler.send_header("X-Accel-Buffering", "no")
                handler.end_headers()
                msg = json.dumps(
                    {
                        "error": (
                            "This log is not a regular file (often linked to stdout/stderr). "
                            "Use docker compose logs, or pick dispatcher.log / filter-test.log."
                        )
                    }
                )
                handler.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                handler.wfile.flush()
                return
        except OSError as e:
            handler.send_error(500, str(e))
            return

    try:
        proc = subprocess.Popen(
            ["/usr/bin/tail", "-F", "-n", "300", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        handler.send_error(500, "Cannot start tail: %s" % e)
        return

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            chunk = line.rstrip("\r\n")
            if len(chunk) > 262144:
                chunk = chunk[:262144] + "…"
            payload = json.dumps({"line": chunk})
            handler.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _version_sort_key(v: str) -> Tuple[int, ...]:
    parts = v.strip().split(".")
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _read_versions() -> list[str]:
    if not VERSIONS_FILE.is_file():
        return []
    lines = VERSIONS_FILE.read_text(encoding="utf-8").splitlines()
    raw = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    return sorted(raw, key=_version_sort_key, reverse=True)


def _read_default_test_paths() -> Dict[str, Any]:
    """Load good_paths / bad_paths for the control UI from JSON (optional file)."""
    if not DEFAULT_TEST_PATHS_FILE.is_file():
        return {"good_paths": [], "bad_paths": []}
    try:
        data = json.loads(DEFAULT_TEST_PATHS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"good_paths": [], "bad_paths": []}
    if not isinstance(data, dict):
        return {"good_paths": [], "bad_paths": []}
    gp = data.get("good_paths")
    bp = data.get("bad_paths")
    out: Dict[str, Any] = {"good_paths": [], "bad_paths": []}
    if isinstance(gp, list):
        out["good_paths"] = [str(x).strip() for x in gp if isinstance(x, str) and str(x).strip()]
    if isinstance(bp, list):
        out["bad_paths"] = [str(x).strip() for x in bp if isinstance(x, str) and str(x).strip()]
    return out


def _load_panel_html() -> bytes:
    if PANEL_HTML.is_file():
        return PANEL_HTML.read_bytes()
    return b"<html><body>control_panel.html missing</body></html>"


def _load_logs_view_html() -> bytes:
    if LOGS_VIEW_HTML.is_file():
        return LOGS_VIEW_HTML.read_bytes()
    return b"<html><body>logs_view.html missing</body></html>"


def _normalize_request_path(raw: str) -> Optional[str]:
    """Return a request-URI path or None if invalid (path-only; no scheme/host)."""
    s = raw.strip()
    if not s:
        return None
    if "://" in s or "\n" in s or "\r" in s:
        return None
    if not s.startswith("/"):
        s = "/" + s
    parts = s.split("/")
    if ".." in parts:
        return None
    if len(s) > 4096:
        return None
    return s


def _absolute_test_url(path: str) -> str:
    return TEST_URL_BASE + path


def _is_safe_test_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return False
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        return False
    return True


def _module_installed() -> bool:
    if not MODULE_VALID_SCRIPT.is_file():
        return False
    try:
        r = subprocess.run(
            [str(MODULE_VALID_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def _dispatcher_log_pos() -> int:
    """Return the current byte offset at the end of dispatcher.log, or 0."""
    try:
        st = DISPATCHER_LOG.stat()
        if stat.S_ISREG(st.st_mode):
            return st.st_size
    except OSError:
        pass
    return 0


def _read_filter_decision(log_pos: int, request_path: str) -> Optional[str]:
    """
    Grep new dispatcher.log lines since log_pos for a Filter rule entry line
    referencing request_path, e.g.:
      Filter rule entry /default-test-container-deny blocked 'GET /admin HTTP/1.1'
    Returns "<decision> — <rule>" or None if not found.
    """
    try:
        st = DISPATCHER_LOG.stat()
        if not stat.S_ISREG(st.st_mode):
            return None
    except OSError:
        return None

    time.sleep(0.12)  # let the dispatcher flush its log buffer

    try:
        with DISPATCHER_LOG.open("rb") as f:
            f.seek(log_pos)
            raw = f.read(131072)
    except OSError:
        return None

    # Match: Filter rule entry <rule-name> blocked|allowed 'METHOD /path...'
    pattern = re.compile(
        r"Filter rule entry\s+(\S+)\s+(blocked|allowed)\s+'[A-Z]+\s+"
        + re.escape(request_path),
        re.IGNORECASE,
    )

    for line in raw.decode("utf-8", errors="replace").splitlines():
        m = pattern.search(line)
        if m:
            return f"{m.group(2).lower()} — {m.group(1)}"

    return None


def _truncate_log(basename: str) -> Optional[str]:
    """Truncate a single log file. Returns an error string, or None on success."""
    if basename not in ALLOWED_LOG_BASENAMES:
        return "Unknown log name"
    path = LOG_DIR / basename
    try:
        path.resolve().relative_to(LOG_DIR.resolve())
    except ValueError:
        return "Invalid path"
    except OSError:
        return "Cannot resolve log directory"
    if not path.exists():
        return None
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            return "Not a regular file"
    except OSError as e:
        return str(e)
    try:
        with open(path, "w"):
            pass
    except OSError as e:
        return str(e)
    return None


def _get_service_health() -> List[Dict[str, str]]:
    """Return supervisord-managed process states via `supervisorctl status`."""
    try:
        r = subprocess.run(
            ["/usr/bin/supervisorctl", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out: List[Dict[str, str]] = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            out.append({
                "name": parts[0],
                "state": parts[1],
                "detail": " ".join(parts[2:]) if len(parts) > 2 else "",
            })
        return out
    except Exception as e:
        return [{"name": "supervisorctl", "state": "ERROR", "detail": str(e)}]


def _restart_httpd_processes() -> None:
    # supervisorctl restart exits non-zero when processes pass through intermediate
    # ERROR/stopped states while cycling — even when they ultimately come up fine.
    # Ignore the exit code and verify the final running state instead.
    result = subprocess.run(
        ["/usr/bin/supervisorctl", "restart", "dispatcher", "renderer"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    health = _get_service_health()
    not_running = [
        s["name"] for s in health
        if s.get("name") in ("dispatcher", "renderer")
        and s.get("state", "").upper() != "RUNNING"
    ]
    if not_running:
        raise subprocess.CalledProcessError(
            result.returncode, result.args,
            output=result.stdout, stderr=result.stderr,
        )


_TEST_USER_AGENT = "aem-dispatcher-filter-tester"


def _fetch_status(url: str, method: str = "GET") -> Tuple[int, Optional[str]]:
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", _TEST_USER_AGENT)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return int(resp.status), None
    except urllib.error.HTTPError as e:
        return int(e.code), None
    except Exception as e:
        return -1, str(e)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Optional[Dict[str, Any]]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0 or length > 256_000:
        return None
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "DispatcherControl/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[control] %s - - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            html = _load_panel_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/api/versions":
            _json_response(self, 200, {"versions": _read_versions()})
            return
        if path == "/api/health":
            _json_response(
                self,
                200,
                {"status": "ok", "module_installed": _module_installed()},
            )
            return
        if path == "/api/module-status":
            _json_response(self, 200, {"installed": _module_installed()})
            return
        if path == "/api/filter-files":
            _json_response(self, 200, {"files": _list_filter_files()})
            return
        if path == "/api/filter-rules":
            _json_response(self, 200, {"rules": _read_filter_rules()})
            return
        if path == "/api/sandbox-mode":
            _json_response(self, 200, {"mode": _read_sandbox_mode()})
            return
        if path == "/api/installed-version":
            ver: Optional[str] = None
            if MODULE_VERSION_FILE.is_file():
                try:
                    ver = MODULE_VERSION_FILE.read_text(encoding="utf-8").strip() or None
                except OSError:
                    pass
            _json_response(self, 200, {"version": ver})
            return
        if path == "/api/prefs":
            _json_response(self, 200, _read_prefs())
            return
        if path == "/api/test-path-files":
            _json_response(self, 200, {"files": _list_test_path_files()})
            return
        if path == "/api/load-test-paths":
            key = (qs.get("key") or [""])[0].strip()
            if ":" not in key:
                _json_response(self, 400, {"ok": False, "error": "Invalid key — expected source:filename"})
                return
            source, filename = key.split(":", 1)
            if source not in ("filters", "tests"):
                _json_response(self, 400, {"ok": False, "error": "source must be 'filters' or 'tests'"})
                return
            if (not filename or os.path.basename(filename) != filename
                    or not filename.endswith(".json")
                    or "/" in filename or "\\" in filename):
                _json_response(self, 400, {"ok": False, "error": "Invalid filename"})
                return
            base_dir = TESTS_DIR if source == "tests" else FILTERS_DIR
            if not (base_dir / filename).is_file():
                _json_response(self, 404, {"ok": False, "error": "File not found"})
                return
            _json_response(self, 200, _read_test_path_file(source, filename))
            return
        if path == "/api/default-test-paths":
            _json_response(self, 200, _read_default_test_paths())
            return
        if path == "/api/service-health":
            _json_response(self, 200, {"services": _get_service_health()})
            return
        if path == "/api/log-tail":
            name = (qs.get("name") or [""])[0].strip()
            try:
                lines = int((qs.get("lines") or ["400"])[0])
            except ValueError:
                lines = 400
            lines = max(50, min(2000, lines))
            content, err = _tail_log_file(name, lines)
            payload: Dict[str, Any] = {"name": name, "lines": lines, "content": content}
            if err:
                payload["error"] = err
            _json_response(self, 200, payload)
            return
        if path == "/logs/view":
            html = _load_logs_view_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/api/log-stream":
            _serve_log_stream(self, qs)
            return
        self.send_error(404, "Not found")

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            html = _load_panel_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/versions":
            body = json.dumps({"versions": _read_versions()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/health":
            body = json.dumps(
                {"status": "ok", "module_installed": _module_installed()}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/module-status":
            body = json.dumps({"installed": _module_installed()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/filter-files":
            body = json.dumps({"files": _list_filter_files()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/default-test-paths":
            body = json.dumps(_read_default_test_paths()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/log-tail":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/logs/view":
            html = _load_logs_view_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/api/log-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/restart-dispatcher":
            try:
                _restart_httpd_processes()
            except subprocess.CalledProcessError as e:
                _json_response(
                    self,
                    500,
                    {
                        "ok": False,
                        "error": "supervisorctl failed",
                        "detail": (e.stderr or e.stdout or str(e))[:4000],
                    },
                )
                return
            except Exception as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            _json_response(self, 200, {"ok": True})
            return

        if path == "/api/dispatcher-version":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            ver = data.get("version")
            if not isinstance(ver, str) or not ver.strip():
                _json_response(self, 400, {"ok": False, "error": "Missing version"})
                return
            ver = ver.strip()
            allowed = set(_read_versions())
            if allowed and ver not in allowed:
                _json_response(
                    self,
                    400,
                    {"ok": False, "error": "Version not in supported list"},
                )
                return
            if not DOWNLOAD_SCRIPT.is_file():
                _json_response(self, 500, {"ok": False, "error": "download script missing"})
                return
            try:
                subprocess.run(
                    [str(DOWNLOAD_SCRIPT), ver],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.CalledProcessError as e:
                _json_response(
                    self,
                    500,
                    {
                        "ok": False,
                        "error": "download_dispatcher failed",
                        "detail": (e.stderr or e.stdout or str(e))[:4000],
                    },
                )
                return
            try:
                _restart_httpd_processes()
            except subprocess.CalledProcessError as e:
                _json_response(
                    self,
                    500,
                    {
                        "ok": False,
                        "error": "download ok but supervisorctl restart failed",
                        "detail": (e.stderr or e.stdout or str(e))[:4000],
                    },
                )
                return
            _write_pref("dispatcher_version", ver)
            _json_response(self, 200, {"ok": True, "version": ver, "prefs_file": PREFS_HOST_DISPLAY})
            return

        if path == "/api/sandbox-mode":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            mode = data.get("mode")
            if mode not in ("deny_all", "allow_all"):
                _json_response(self, 400, {"ok": False, "error": "mode must be 'deny_all' or 'allow_all'"})
                return
            content = _SANDBOX_ALLOW if mode == "allow_all" else _SANDBOX_DENY
            try:
                SANDBOX_POLICY_FILE.write_text(content, encoding="utf-8")
            except OSError as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            try:
                _restart_httpd_processes()
            except subprocess.CalledProcessError as e:
                _json_response(self, 500, {"ok": False, "error": "policy saved but restart failed",
                                           "detail": (e.stderr or e.stdout or str(e))[:2000]})
                return
            _write_pref("sandbox_mode", mode)
            _json_response(self, 200, {"ok": True, "mode": mode, "prefs_file": PREFS_HOST_DISPLAY})
            return

        if path == "/api/save-filters":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            content = data.get("content")
            if not isinstance(content, str):
                _json_response(self, 400, {"ok": False, "error": "Missing content"})
                return
            if len(content) > 512_000:
                _json_response(self, 400, {"ok": False, "error": "Content too large (max 512 KB)"})
                return
            filename = data.get("filename", "002_web_filters.any")
            # Validate: basename only, must end in .any, no path separators
            import os as _os
            if (not isinstance(filename, str) or
                    _os.path.basename(filename) != filename or
                    not filename.endswith(".any") or
                    "/" in filename or "\\" in filename):
                _json_response(self, 400, {"ok": False, "error": "Invalid filename"})
                return
            target = FILTERS_DIR / filename
            try:
                target.write_text(content, encoding="utf-8")
            except OSError as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            _json_response(self, 200, {"ok": True, "file": filename})
            return

        if path == "/api/save-test-paths":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            filename = data.get("filename", "web_test_paths.json")
            if (not isinstance(filename, str)
                    or os.path.basename(filename) != filename
                    or not filename.endswith("_test_paths.json")
                    or "/" in filename or "\\" in filename):
                _json_response(self, 400, {"ok": False, "error": "Filename must end in _test_paths.json"})
                return
            good_paths = data.get("good_paths", [])
            bad_paths  = data.get("bad_paths",  [])
            if not isinstance(good_paths, list) or not isinstance(bad_paths, list):
                _json_response(self, 400, {"ok": False, "error": "good_paths and bad_paths must be arrays"})
                return
            payload = {"good_paths": good_paths, "bad_paths": bad_paths}
            try:
                (FILTERS_DIR / filename).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            except OSError as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            _json_response(self, 200, {"ok": True, "filename": filename, "saved_path": "./filters/" + filename})
            return

        if path == "/api/truncate-log":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            name = data.get("name")
            if not isinstance(name, str) or not name.strip():
                _json_response(self, 400, {"ok": False, "error": "Missing name"})
                return
            err = _truncate_log(name.strip())
            if err:
                status = 400 if err in ("Unknown log name", "Invalid path", "Not a regular file") else 500
                _json_response(self, status, {"ok": False, "error": err})
                return
            _json_response(self, 200, {"ok": True, "name": name.strip()})
            return

        if path == "/api/truncate-all-logs":
            errors: List[Dict[str, str]] = []
            for basename in sorted(ALLOWED_LOG_BASENAMES):
                err = _truncate_log(basename)
                if err and err not in ("Unknown log name", "Not a regular file"):
                    errors.append({"name": basename, "error": err})
            if errors:
                _json_response(self, 500, {"ok": False, "errors": errors})
                return
            _json_response(self, 200, {"ok": True})
            return

        if path == "/api/test-urls":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            good_raw = data.get("good_paths")
            bad_raw = data.get("bad_paths")
            if not isinstance(good_raw, list) or not isinstance(bad_raw, list):
                _json_response(
                    self,
                    400,
                    {"ok": False, "error": "good_paths and bad_paths must be arrays of request paths"},
                )
                return

            _HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

            def run_group(paths: List[Any], expect: int) -> List[Dict[str, Any]]:
                out: List[Dict[str, Any]] = []
                for item in paths:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    raw_in = item.strip()
                    # Parse optional "METHOD PATH" format, e.g. "POST /api/endpoint"
                    method = "GET"
                    parts = raw_in.split(None, 1)
                    if len(parts) == 2 and parts[0].upper() in _HTTP_METHODS:
                        method, raw_path = parts[0].upper(), parts[1]
                    else:
                        raw_path = raw_in
                    norm = _normalize_request_path(raw_path)
                    if not norm:
                        out.append(
                            {
                                "path": raw_in,
                                "url": None,
                                "status": None,
                                "expect": expect,
                                "ok": False,
                                "error": (
                                    "Invalid path — use request-URI only "
                                    "(e.g. /content/page.html or GET /content/page.html), not a full URL or .."
                                ),
                            }
                        )
                        continue
                    url = _absolute_test_url(norm)
                    if not _is_safe_test_url(url):
                        out.append(
                            {
                                "path": norm,
                                "url": url,
                                "status": None,
                                "expect": expect,
                                "ok": False,
                                "error": (
                                    "Resolved URL not allowed for this sandbox "
                                    "(use paths hit via 127.0.0.1 / localhost on allowed ports; "
                                    "set TEST_URL_BASE if needed)"
                                ),
                            }
                        )
                        continue
                    log_pos = _dispatcher_log_pos()
                    code, err = _fetch_status(url, method)
                    ok = code == expect and err is None
                    row: Dict[str, Any] = {
                        "path": norm,
                        "method": method,
                        "url": url,
                        "status": code,
                        "expect": expect,
                        "ok": ok,
                    }
                    if err:
                        row["error"] = err
                    filter_decision = _read_filter_decision(log_pos, norm)
                    if filter_decision is not None:
                        row["filter_log"] = filter_decision
                    out.append(row)
                return out

            payload = {
                "ok": True,
                "test_url_base": TEST_URL_BASE,
                "sandbox_mode": _read_sandbox_mode(),
                "filter_files": _list_filter_files(),
                "filter_rules": _read_filter_rules(),
                "good": run_group(good_raw, 200),
                "bad": run_group(bad_raw, 404),
            }
            _json_response(self, 200, payload)
            return

        self.send_error(404, "Not found")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), ControlHandler)
    sys.stderr.write("Control panel listening on 0.0.0.0:%s\n" % CONTROL_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

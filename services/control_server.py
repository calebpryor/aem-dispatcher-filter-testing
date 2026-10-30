#!/usr/bin/env python3.9
"""
Local control plane for the dispatcher sandbox: version selection, httpd restart,
path-based URL smoke tests, and log browsing. Binds CONTROL_PORT (default 59173);
not intended for exposure beyond the developer machine.

Pages: / (control panel), /logs/view?name=… (log stream UI; SSE via /api/log-stream).
Tests POST JSON { good_paths, bad_paths, blocked_paths } with request lines of the form
  [METHOD] /path?query [-H 'Name: value'] [-d 'body'] [-A 'user agent'] [--expect 403]
URLs are built with TEST_URL_BASE (default http://127.0.0.1).

ModSecurity rules (no built-ins — customers copy their own *.conf/*.data files
into ./modsecurity/) are managed by modsec_config.py: per-rule block / logonly / off
choices, and every change is syntax-checked on a staged copy (httpd -t) before going live.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modsec_config as msc  # noqa: E402

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
        "modsec_audit.log",
        "modsec_debug.log",
    }
)
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
ALLOWED_PORTS = frozenset({80, 4503, 8080, 18080, 55555, 59173})

ERROR_LOG = LOG_DIR / "error_log"


def _list_test_path_files() -> List[Dict[str, str]]:
    """Return all loadable test path JSON files from the tests/ directory.

    Each entry has 'key' (used as the load identifier, format "tests:filename"),
    'label' (display name), and 'source' ("tests").
    """
    entries: List[Dict[str, str]] = []
    if TESTS_DIR.is_dir():
        for p in sorted(TESTS_DIR.glob("*.json")):
            if p.is_file():
                entries.append({"key": "tests:" + p.name, "label": p.name, "source": "tests"})
    return entries


_TEST_PATH_KEYS = ("good_paths", "bad_paths", "blocked_paths")


def _read_test_path_file(source: str, filename: str) -> Dict[str, Any]:
    base_dir = TESTS_DIR if source == "tests" else FILTERS_DIR
    p = base_dir / filename
    empty: Dict[str, Any] = {k: [] for k in _TEST_PATH_KEYS}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    out: Dict[str, Any] = {k: [] for k in _TEST_PATH_KEYS}
    for key in _TEST_PATH_KEYS:
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
    """Load good_paths / bad_paths / blocked_paths for the control UI from JSON (optional file)."""
    if not DEFAULT_TEST_PATHS_FILE.is_file():
        return {k: [] for k in _TEST_PATH_KEYS}
    return _read_test_path_file("tests", DEFAULT_TEST_PATHS_FILE.name)


def _load_panel_html() -> bytes:
    if PANEL_HTML.is_file():
        return PANEL_HTML.read_bytes()
    return b"<html><body>control_panel.html missing</body></html>"


def _load_logs_view_html() -> bytes:
    if LOGS_VIEW_HTML.is_file():
        return LOGS_VIEW_HTML.read_bytes()
    return b"<html><body>logs_view.html missing</body></html>"


_SCHEME_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
# Everything printable except space and '#', so attack payloads (quotes, <>, .., %xx)
# reach Apache untouched while the request line stays valid.
_PATH_SAFE_CHARS = "".join(chr(c) for c in range(33, 127) if chr(c) != "#")


def _normalize_request_path(raw: str) -> Optional[str]:
    """Return a request-URI path or None if invalid (path-only; no scheme/host).

    Query strings and payloads such as ../, quotes or full URLs inside the query are
    allowed — the request always goes to TEST_URL_BASE (checked by _is_safe_test_url).
    """
    s = raw.strip()
    if not s:
        return None
    if _SCHEME_PREFIX_RE.match(s) or "\n" in s or "\r" in s:
        return None
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 4096:
        return None
    return s


def _encode_request_path(path: str) -> str:
    return quote(path, safe=_PATH_SAFE_CHARS)


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report 3xx responses as-is (e.g. a ModSecurity redirect: action) instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch_status(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[str] = None,
) -> Tuple[int, Optional[str], Dict[str, str]]:
    """Return (status, error, response_headers)."""
    data = body.encode("utf-8") if body is not None else None
    try:
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", _TEST_USER_AGENT)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with _NO_REDIRECT_OPENER.open(req, timeout=20) as resp:
            return int(resp.status), None, dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        return int(e.code), None, dict(e.headers.items()) if e.headers else {}
    except Exception as e:
        return -1, str(e), {}


_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
# Options taking a value. Same spelling as curl so existing curl test commands can be pasted as-is.
_VALUE_OPTS = {
    "-H", "--header", "-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode",
    "-A", "--user-agent", "-e", "--referer", "-b", "--cookie", "-X", "--request",
    "--expect", "--rule",
    # curl output options accepted and ignored
    "-o", "--output", "-w", "--write-out", "-m", "--max-time", "--connect-timeout",
}
_FLAG_OPTS = {"--path-as-is", "-s", "--silent", "-S", "--show-error", "-k", "--insecure", "-i", "--include",
              "-v", "--verbose", "-L", "--location", "--compressed", "-sS", "-ks", "-sk", "-sL", "-g", "--globoff"}
# First option marks the end of "[METHOD] PATH" (the path itself may contain spaces/quotes).
_TEST_OPT_START_RE = re.compile(
    r"\s(?=(?:%s)(?:\s|$))" % "|".join(re.escape(o) for o in sorted(_VALUE_OPTS | _FLAG_OPTS, key=len, reverse=True))
)
_EXPECT_RE = re.compile(r"^(!?)([1-5]\d\d)$")


def _apply_test_options(tokens: List[str], spec: Dict[str, Any]) -> Optional[str]:
    """Apply curl-style options to spec; returns an error message or None."""
    i = 0
    while i < len(tokens):
        opt = tokens[i]
        if opt in _FLAG_OPTS:
            i += 1
            continue
        if opt not in _VALUE_OPTS:
            if not opt.startswith("-") and spec.get("_curl") and spec.get("path") is None:
                spec["path"] = opt  # the URL in a pasted curl command
                i += 1
                continue
            return "Unknown option %r" % opt
        if i + 1 >= len(tokens):
            return "Option %s needs a value" % opt
        val = tokens[i + 1]
        i += 2
        if opt in ("-H", "--header"):
            if ":" not in val:
                return "Header must look like 'Name: value' (got %r)" % val
            k, v = val.split(":", 1)
            if not k.strip() or "\n" in val or "\r" in val:
                return "Invalid header %r" % val
            spec["headers"][k.strip()] = v.strip()
        elif opt in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"):
            spec["bodies"].append(val)
        elif opt in ("-A", "--user-agent"):
            spec["headers"]["User-Agent"] = val
        elif opt in ("-e", "--referer"):
            spec["headers"]["Referer"] = val
        elif opt in ("-b", "--cookie"):
            spec["headers"]["Cookie"] = val
        elif opt in ("-X", "--request"):
            if val.upper() not in _HTTP_METHODS:
                return "Unsupported method %r" % val
            spec["method"] = val.upper()
        elif opt == "--expect":
            if not _EXPECT_RE.match(val.strip()):
                return "--expect must be a status code like 403, or !403 for 'anything but 403' (got %r)" % val
            spec["expect"] = val.strip()
        elif opt == "--rule":
            for rid in val.split(","):
                if not rid.strip().isdigit():
                    return "--rule must be a ModSecurity rule id (got %r)" % val
                spec["rules"].append(rid.strip())
    return None


def _parse_test_line(raw: str) -> Dict[str, Any]:
    """
    Parse a test line. Two forms are accepted:
      [METHOD] /path?query [options]
      curl [curl options] 'http://host/path?query' [options]   (e.g. pasted from existing curl tests)
    Options: -H 'Name: value', -d 'body' (repeatable, joined with &), -A agent, -e referer,
    -b cookie, -X METHOD, --expect 403 | --expect '!403', --rule <id>[,<id>] (rule must fire).
    Returns {"method","path","headers","body","expect","rules"} or {"error": "..."}.
    """
    spec: Dict[str, Any] = {"method": None, "path": None, "headers": {}, "bodies": [], "expect": None, "rules": []}
    if re.match(r"^curl\s", raw):
        try:
            tokens = shlex.split(raw)[1:]
        except ValueError as e:
            return {"error": "Could not parse curl command (%s) — check quoting" % e}
        spec["_curl"] = True
        err = _apply_test_options(tokens, spec)
        if err:
            return {"error": err}
        if not spec["path"]:
            return {"error": "No URL found in curl command"}
        url = spec["path"]
        m = re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://)?([^/?#]*)(.*)$", url) if "://" in url else None
        if m:
            host = m.group(1).rsplit("@", 1)[-1]
            hostname = host.split(":", 1)[0].strip("[]").lower()
            if hostname and hostname not in ALLOWED_HOSTS and not any(k.lower() == "host" for k in spec["headers"]):
                spec["headers"]["Host"] = host  # keep the vhost the command was aimed at
            spec["path"] = m.group(2) or "/"
    else:
        m = _TEST_OPT_START_RE.search(raw)
        head, opt_str = (raw[: m.start()], raw[m.end():]) if m else (raw, "")
        parts = head.strip().split(None, 1)
        if len(parts) == 2 and parts[0].upper() in _HTTP_METHODS:
            spec["method"], spec["path"] = parts[0].upper(), parts[1].strip()
        else:
            spec["path"] = head.strip()
        try:
            tokens = shlex.split(opt_str) if opt_str else []
        except ValueError as e:
            return {"error": "Could not parse options (%s) — check quoting" % e}
        err = _apply_test_options(tokens, spec)
        if err:
            return {"error": err}
    body = "&".join(spec["bodies"]) if spec["bodies"] else None
    method = spec["method"]
    headers = spec["headers"]
    if body is not None:
        method = method or "POST"
        if not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = "application/x-www-form-urlencoded"
    return {"method": method or "GET", "path": spec["path"], "headers": headers, "body": body,
            "expect": spec["expect"], "rules": spec["rules"]}


def _status_matches(status: int, expect: Any) -> bool:
    if isinstance(expect, str) and expect.startswith("!"):
        return status > 0 and status != int(expect[1:])
    return status == int(expect)


# ── ModSecurity ──────────────────────────────────────────────────────────────


def _modsec_overview() -> Dict[str, Any]:
    """Rule families with their modes, rule IDs, data references and problems, for the UI."""
    p = msc.plan()
    active = set(p["active"])
    fams_out: List[Dict[str, Any]] = []
    for fam in p["families"]:
        variants: Dict[str, Any] = {}
        for vname, rel in fam["variants"].items():
            variants[vname] = {
                "file": rel,
                "active": rel in active,
                "rule_ids": msc.rule_ids(rel),
                "data_refs": msc.referenced_data(rel),
            }
        fams_out.append({"key": fam["key"], "kind": fam["kind"], "mode": p["modes"][fam["key"]],
                         "variants": variants})
    missing = sorted({r["rel"] or r["ref"] for rel in p["active"] for r in msc.referenced_data(rel) if not r["exists"]})
    return {
        "families": fams_out,
        "active": p["active"],
        "data_files": msc.data_files(),
        "duplicate_ids": msc.duplicate_ids(p["active"]),
        "missing_data": missing,
        "rules_dir": msc.RULES_HOST_DISPLAY,
    }


def _read_modsec_file(rel: str) -> Optional[str]:
    p = msc.RULES_DIR / rel
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) > msc.MAX_FILE_CHARS:
        text = text[: msc.MAX_FILE_CHARS] + "\n... [truncated] ..."
    return text


def _apply_modsec(modes: Optional[Dict[str, str]] = None, settings: Optional[Dict[str, Any]] = None,
                  file_overrides: Optional[Dict[str, str]] = None, restart: bool = True) -> Tuple[int, Dict[str, Any]]:
    """Validate a candidate ModSecurity config on a staged copy; if valid, make it live (and restart)."""
    v = msc.validate(modes, settings, file_overrides)
    result: Dict[str, Any] = {"valid": v["valid"], "output": v["output"], "duplicate_ids": v["duplicate_ids"],
                              "placeholders": v["placeholders"]}
    if v["valid"] is False:
        return 400, dict(result, ok=False, error="httpd config test failed — nothing was changed")
    try:
        for rel, content in (file_overrides or {}).items():
            target = msc.RULES_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        updates: Dict[str, Any] = {}
        if modes is not None:
            updates["modsec_rules"] = v["modes"]
        if settings is not None:
            updates["modsec_engine"] = settings["engine"]
            updates["modsec_debug_level"] = settings["debug_level"]
        if updates:
            msc.write_prefs(updates)
        live = msc.apply_live()
    except OSError as e:
        return 500, dict(result, ok=False, error=str(e))
    result.update(active=live["active"], placeholders=live["placeholders"] or v["placeholders"])
    restarted = False
    if restart and v["valid"]:
        try:
            _restart_httpd_processes()
            restarted = True
        except subprocess.CalledProcessError as e:
            return 500, dict(result, ok=False, error="config saved but restart failed",
                             detail=(e.stderr or e.stdout or str(e))[:2000])
    return 200, dict(result, ok=True, restarted=restarted, prefs_file=PREFS_HOST_DISPLAY)


def _error_log_pos() -> int:
    try:
        st = ERROR_LOG.stat()
        if stat.S_ISREG(st.st_mode):
            return st.st_size
    except OSError:
        pass
    return 0


def _modsec_tag(line: str, name: str) -> Optional[str]:
    m = re.search(r'\[%s "((?:[^"\\]|\\.)*)"\]' % name, line)
    return m.group(1) if m else None


def _read_modsec_events(log_pos: int, request_id: Optional[str], request_path: str) -> List[Dict[str, Any]]:
    """
    Collect ModSecurity error_log entries written since log_pos for one test request.
    Matched by unique_id (X-Sandbox-Request-Id response header) when available, else by URI.
    """
    try:
        if not stat.S_ISREG(ERROR_LOG.stat().st_mode):
            return []
        with ERROR_LOG.open("rb") as f:
            f.seek(log_pos)
            raw = f.read(262144).decode("utf-8", errors="replace")
    except OSError:
        return []
    uri = request_path.split("?", 1)[0]
    events: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        idx = line.find("ModSecurity: ")
        if idx < 0:
            continue
        uid = _modsec_tag(line, "unique_id")
        if request_id and request_id != "(null)":
            if uid != request_id:
                continue
        elif _modsec_tag(line, "uri") not in (uri, _encode_request_path(uri)):
            continue
        detail = line[idx + len("ModSecurity: "):]
        cut = detail.find(' [file "')
        if cut >= 0:
            detail = detail[:cut]
        summary = detail.split(". ", 1)[0].rstrip(".")
        events.append({
            "id": _modsec_tag(line, "id"),
            "msg": _modsec_tag(line, "msg"),
            "severity": _modsec_tag(line, "severity"),
            "summary": summary,
            "detail": detail[:2000],
            "disruptive": not summary.startswith("Warning"),
        })
    return events


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
        if path == "/api/modsec-settings":
            _json_response(self, 200, dict(msc.engine_settings(), rules_dir=msc.RULES_HOST_DISPLAY))
            return
        if path == "/api/test-scope":
            _json_response(self, 200, {"scope": msc.test_scope()})
            return
        if path == "/api/modsec-rules":
            _json_response(self, 200, _modsec_overview())
            return
        if path == "/api/modsec-file":
            rel = msc.safe_rel_path((qs.get("file") or [""])[0].strip())
            if not rel or not rel.endswith(msc.EDITABLE_SUFFIXES):
                _json_response(self, 400, {"ok": False, "error": "Invalid file"})
                return
            content = _read_modsec_file(rel)
            if content is None:
                _json_response(self, 404, {"ok": False, "error": "File not found"})
                return
            _json_response(self, 200, {"ok": True, "file": rel, "content": content})
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

        if path == "/api/modsec-settings":
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            settings = msc.engine_settings()
            engine = data.get("engine", settings["engine"])
            level = data.get("debug_level", settings["debug_level"])
            if engine not in msc.ENGINE_MODES or level not in msc.DEBUG_LEVELS:
                _json_response(self, 400, {"ok": False, "error": "engine must be On, DetectionOnly or Off; debug_level one of %s" % (msc.DEBUG_LEVELS,)})
                return
            status, payload = _apply_modsec(settings={"engine": engine, "debug_level": level})
            _json_response(self, status, dict(payload, engine=engine, debug_level=level))
            return

        if path == "/api/test-scope":
            data = _read_json_body(self)
            scope = (data or {}).get("scope")
            if scope not in msc.TEST_SCOPES:
                _json_response(self, 400, {"ok": False, "error": "scope must be one of %s" % (msc.TEST_SCOPES,)})
                return
            try:
                msc.write_prefs({"test_scope": scope})
                msc.write_filter_scope(scope)
                msc.apply_live()
            except OSError as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            try:
                _restart_httpd_processes()
            except subprocess.CalledProcessError as e:
                _json_response(self, 500, {"ok": False, "error": "scope saved but restart failed",
                                           "detail": (e.stderr or e.stdout or str(e))[:2000]})
                return
            _json_response(self, 200, {"ok": True, "scope": scope, "prefs_file": PREFS_HOST_DISPLAY})
            return

        if path == "/api/modsec-modes":
            data = _read_json_body(self)
            modes = (data or {}).get("modes")
            if not isinstance(modes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in modes.items()):
                _json_response(self, 400, {"ok": False, "error": "modes must be an object of {rule_key: mode}"})
                return
            merged = dict(msc.plan()["modes"])
            merged.update(modes)
            status, payload = _apply_modsec(modes=merged)
            _json_response(self, status, payload)
            return

        if path in ("/api/modsec-validate", "/api/modsec-save"):
            data = _read_json_body(self)
            if not data:
                _json_response(self, 400, {"ok": False, "error": "Invalid JSON body"})
                return
            rel = msc.safe_rel_path(data.get("filename") or "")
            content = data.get("content")
            if not rel or not rel.endswith(msc.EDITABLE_SUFFIXES):
                _json_response(self, 400, {"ok": False, "error": (
                    "File must be a .conf or .data path inside ./modsecurity/ "
                    "(letters, digits, . _ - @ + and / only)"
                )})
                return
            if not isinstance(content, str):
                _json_response(self, 400, {"ok": False, "error": "Missing content"})
                return
            if len(content) > msc.MAX_FILE_CHARS:
                _json_response(self, 400, {"ok": False, "error": "Content too large (max 512 KB)"})
                return
            if path == "/api/modsec-validate":
                v = msc.validate(file_overrides={rel: content})
                _json_response(self, 200, {"ok": v["valid"] is not False, "file": rel, "valid": v["valid"],
                                           "output": v["output"], "duplicate_ids": v["duplicate_ids"],
                                           "placeholders": v["placeholders"]})
                return
            restart = bool(data.get("restart"))
            status, payload = _apply_modsec(file_overrides={rel: content}, restart=restart)
            _json_response(self, status, dict(payload, file=rel, saved_path=msc.RULES_HOST_DISPLAY + rel))
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
                    or "/" in filename or "\\" in filename
                    or filename == "default_test_paths.json"):
                _json_response(self, 400, {"ok": False, "error": "Filename must end in _test_paths.json and cannot be default_test_paths.json"})
                return
            payload = {k: data.get(k, []) for k in _TEST_PATH_KEYS}
            if not all(isinstance(v, list) for v in payload.values()):
                _json_response(self, 400, {"ok": False, "error": "good_paths, bad_paths and blocked_paths must be arrays"})
                return
            try:
                (TESTS_DIR / filename).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            except OSError as e:
                _json_response(self, 500, {"ok": False, "error": str(e)})
                return
            _json_response(self, 200, {"ok": True, "filename": filename, "saved_path": "./tests/" + filename})
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
            blocked_raw = data.get("blocked_paths", [])
            if not all(isinstance(v, list) for v in (good_raw, bad_raw, blocked_raw)):
                _json_response(
                    self,
                    400,
                    {"ok": False, "error": "good_paths, bad_paths and blocked_paths must be arrays of request paths"},
                )
                return

            def run_group(paths: List[Any], default_expect: int) -> List[Dict[str, Any]]:
                out: List[Dict[str, Any]] = []
                for item in paths:
                    if not isinstance(item, str) or not item.strip():
                        continue
                    raw_in = item.strip()
                    spec = _parse_test_line(raw_in)
                    if "error" in spec:
                        out.append({"path": raw_in, "url": None, "status": None,
                                    "expect": default_expect, "ok": False, "error": spec["error"]})
                        continue
                    method = spec["method"]
                    expect: Any = spec["expect"] or default_expect
                    if isinstance(expect, str) and not expect.startswith("!"):
                        expect = int(expect)
                    norm = _normalize_request_path(spec["path"])
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
                                    "(e.g. /content/page.html or GET /content/page.html), not a full URL"
                                ),
                            }
                        )
                        continue
                    url = _absolute_test_url(_encode_request_path(norm))
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
                    err_pos = _error_log_pos()
                    code, err, resp_headers = _fetch_status(url, method, spec["headers"], spec["body"])
                    ok = err is None and _status_matches(code, expect)
                    row: Dict[str, Any] = {
                        "path": norm,
                        "method": method,
                        "url": url,
                        "status": code,
                        "expect": expect,
                        "ok": ok,
                    }
                    if spec["headers"]:
                        row["headers"] = spec["headers"]
                    if spec["body"] is not None:
                        row["body"] = spec["body"]
                    if err:
                        row["error"] = err
                    filter_decision = _read_filter_decision(log_pos, _encode_request_path(norm))
                    if filter_decision is not None:
                        row["filter_log"] = filter_decision
                    request_id = next((v for k, v in resp_headers.items()
                                       if k.lower() == "x-sandbox-request-id"), None)
                    events = _read_modsec_events(err_pos, request_id, norm)
                    if events:
                        row["modsec"] = events
                    if spec["rules"]:
                        fired = {ev.get("id") for ev in events}
                        missing = [rid for rid in spec["rules"] if rid not in fired]
                        row["rules_expected"] = spec["rules"]
                        if missing:
                            row["rules_missing"] = missing
                            row["ok"] = False
                    out.append(row)
                return out

            payload = {
                "ok": True,
                "test_url_base": TEST_URL_BASE,
                "sandbox_mode": _read_sandbox_mode(),
                "filter_files": _list_filter_files(),
                "filter_rules": _read_filter_rules(),
                "test_scope": msc.test_scope(),
                "modsec": msc.engine_settings(),
                "modsec_files": msc.plan()["active"],
                "good": run_group(good_raw, 200),
                "bad": run_group(bad_raw, 404),
                "blocked": run_group(blocked_raw, 403),
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

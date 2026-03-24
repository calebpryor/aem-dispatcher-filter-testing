#!/bin/bash
# Block until mod_dispatcher.so is installed via the control panel, then exec httpd.
# Args: __default__ (main server config) or path to alternate config file.
set -e
CONF_TYPE="${1:?}"

echo "[wait_httpd] Waiting for mod_dispatcher.so — install it from the control panel (port ${CONTROL_PORT:-59173})..." >&2

n=0
while ! /usr/local/bin/disp_module_valid.sh; do
	n=$((n + 1))
	if [ "$((n % 15))" -eq 0 ]; then
		echo "[wait_httpd] Still waiting — open http://127.0.0.1:${CONTROL_PORT:-59173} and use \"Download & switch module\"" >&2
	fi
	sleep 2
done

echo "[wait_httpd] mod_dispatcher.so present, starting httpd..." >&2
if [ "$CONF_TYPE" = "__default__" ]; then
	exec /usr/sbin/httpd -D FOREGROUND
else
	exec /usr/sbin/httpd -D FOREGROUND -f "$CONF_TYPE"
fi

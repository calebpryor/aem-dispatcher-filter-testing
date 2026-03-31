#!/bin/bash
# mod_dispatcher.so is not downloaded at container start. Install it only from the
# control panel (download_dispatcher.sh via /api/dispatcher-version). Httpd processes
# wait in wait_httpd.sh until the module file is valid.

CP="${CONTROL_PORT:-59173}"
echo "Dispatcher module: use the control UI at http://127.0.0.1:${CP} (Download & switch module). Apache will start after the .so is installed."

# Restore sandbox policy from prefs file (persisted in bind-mounted filters dir), else deny_all
POLICY_FILE="/etc/httpd/conf.dispatcher.d/sandbox_policy.any"
PREFS_FILE="/etc/httpd/conf.dispatcher.d/filters/.prefs.json"
SANDBOX_MODE="deny_all"
if [ -f "$PREFS_FILE" ]; then
    SAVED_MODE=$(python3 -c "import json,sys; d=json.load(open('$PREFS_FILE')); print(d.get('sandbox_mode','deny_all'))" 2>/dev/null)
    if [ "$SAVED_MODE" = "allow_all" ] || [ "$SAVED_MODE" = "deny_all" ]; then
        SANDBOX_MODE="$SAVED_MODE"
    fi
fi
if [ "$SANDBOX_MODE" = "allow_all" ]; then
    printf '# mode: allow_all\n/sandbox-default { /type "allow" /url "*" }\n' > "$POLICY_FILE"
    echo "Restored sandbox policy from prefs: allow_all"
else
    printf '# mode: deny_all\n/sandbox-default { /type "deny" /url "*" }\n' > "$POLICY_FILE"
    echo "Restored sandbox policy from prefs: deny_all"
fi

# Create default filter file if no *_filters.any files exist (prevents empty dropdown)
FILTERS_DIR="/etc/httpd/conf.dispatcher.d/filters"
if ! ls "$FILTERS_DIR"/*_filters.any 2>/dev/null | grep -q .; then
    touch "$FILTERS_DIR/002_web_filters.any"
    echo "Created default filter file: 002_web_filters.any"
fi

echo "Starting filter file watcher..."
/usr/local/bin/watch_filters.sh &

echo "Starting filter log extractor..."
/usr/local/bin/filter_log_extractor.sh &

/usr/bin/supervisord -j /var/run/supervisor/supervisord.pid

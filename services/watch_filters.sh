#!/bin/bash

# Script to watch for changes to *_filters.any files and ModSecurity rule files (*.conf / *.data)
# and restart dispatcher httpd
FILTERS_DIR="/etc/httpd/conf.dispatcher.d/filters"
MODSEC_RULES_DIR="/etc/httpd/modsecurity.d/rules"
LOG_PREFIX="[FILTER-WATCHER]"

echo "$LOG_PREFIX Starting file watcher for directories: $FILTERS_DIR $MODSEC_RULES_DIR"

# Function to restart dispatcher httpd
restart_dispatcher() {
    echo "$LOG_PREFIX Filter files changed, restarting dispatcher..."
    # Shared lock with the control panel (see modsec_config.py) so restarts never overlap.
    flock /tmp/sandbox-httpd-restart.lock supervisorctl restart dispatcher
    if [ $? -eq 0 ]; then
        echo "$LOG_PREFIX Dispatcher restarted successfully"
    else
        echo "$LOG_PREFIX Failed to restart dispatcher"
    fi
}

# Watch for file changes, creations, and deletions
inotifywait -m -r -e close_write,create,delete,move --format '%w%f %e' "$FILTERS_DIR" "$MODSEC_RULES_DIR" | while read FILE EVENT
do
    # Check if the file is a *_filters.any file
    if [[ "$FILE" == *_filters.any ]]; then
        echo "$LOG_PREFIX Detected $EVENT on filter file: $FILE"
        restart_dispatcher
    elif [[ "$FILE" == "$MODSEC_RULES_DIR"/* && ( "$FILE" == *.conf || "$FILE" == *.data ) && "$(basename "$FILE")" != .* ]]; then
        echo "$LOG_PREFIX Detected $EVENT on ModSecurity file: $FILE"
        # Copying a whole rule set fires many events — wait until things settle for 2s.
        while read -t 2 MORE_FILE MORE_EVENT; do :; done
        # Regenerates the include list, runs httpd -t on a staged copy and restarts only if valid.
        /usr/bin/python3.9 /usr/local/bin/modsec_config.py apply --restart
    fi
done

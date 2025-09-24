#!/bin/bash

# Script to watch for changes to *_filters.any files and restart dispatcher httpd
FILTERS_DIR="/etc/httpd/conf.dispatcher.d/filters"
LOG_PREFIX="[FILTER-WATCHER]"

echo "$LOG_PREFIX Starting filter file watcher for directory: $FILTERS_DIR"

# Function to restart dispatcher httpd
restart_dispatcher() {
    echo "$LOG_PREFIX Filter files changed, restarting dispatcher..."
    supervisorctl restart dispatcher
    if [ $? -eq 0 ]; then
        echo "$LOG_PREFIX Dispatcher restarted successfully"
    else
        echo "$LOG_PREFIX Failed to restart dispatcher"
    fi
}

# Watch for file changes, creations, and deletions
inotifywait -m -r -e create,modify,delete,move --format '%w%f %e' "$FILTERS_DIR" | while read FILE EVENT
do
    # Check if the file is a *_filters.any file
    if [[ "$FILE" == *_filters.any ]]; then
        echo "$LOG_PREFIX Detected $EVENT on filter file: $FILE"
        restart_dispatcher
    fi
done

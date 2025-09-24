#!/bin/bash

# Script to extract filter-related log entries from dispatcher.log to filter-test.log
DISPATCHER_LOG="/var/log/httpd/dispatcher.log"
FILTER_LOG="/var/log/httpd/filter-test.log"
LOG_PREFIX="[FILTER-LOG-EXTRACTOR]"

echo "$LOG_PREFIX Starting filter log extractor..."
echo "$LOG_PREFIX Monitoring: $DISPATCHER_LOG"
echo "$LOG_PREFIX Output to: $FILTER_LOG"

# Ensure the log directory exists and is writable
mkdir -p "$(dirname "$FILTER_LOG")"

# Clean up old logs on startup (except filter-test.log which gets truncated)
echo "$LOG_PREFIX Cleaning up old log files..."
find "$(dirname "$FILTER_LOG")" -type f -name "*.log" ! -name "filter-test.log" -delete 2>/dev/null || true

# Truncate filter-test.log on startup (clear content but keep file)
echo "$LOG_PREFIX Truncating filter-test.log on startup..."
> "$FILTER_LOG"

# Wait for dispatcher log file to exist
echo "$LOG_PREFIX Waiting for dispatcher log file to be available..."
while [ ! -f "$DISPATCHER_LOG" ]; do
    sleep 1
done
echo "$LOG_PREFIX Dispatcher log file found, starting monitoring..."

# Function to extract filter-related log entries and also forward to stdout
extract_filter_logs() {
    local skip_until_next_request=false
    local buffer=()
    local current_tid=""
    
    # Monitor the dispatcher log file and extract filter-related entries
    tail -F "$DISPATCHER_LOG" 2>/dev/null | while read line; do
        # Forward all dispatcher logs to stdout for container logging
        echo "$line"
        
        # Extract thread ID from the log line for tracking request sequences
        local tid=$(echo "$line" | grep -oE "tid [0-9]+" | cut -d' ' -f2)
        
        # Check if this is the start of a new request (method line)
        if echo "$line" | grep -q "method :"; then
            # If we have a different thread ID, flush any buffered lines first
            if [ -n "$current_tid" ] && [ "$tid" != "$current_tid" ] && [ ${#buffer[@]} -gt 0 ] && [ "$skip_until_next_request" = false ]; then
                printf '%s\n' "${buffer[@]}" >> "$FILTER_LOG"
            fi
            # Reset for new request
            buffer=()
            skip_until_next_request=false
            current_tid="$tid"
        fi
        
        # Match lines containing filter-related information
        if echo "$line" | grep -qE "(Filter rule entry|allowed|blocked|Filter rejects|Decomposing URL|method :|uri :|path :|extension :|selector|suffix :|query :)"; then
            # Check if this request involves favicon or container-404.html (check current line and buffer)
            if echo "$line" | grep -qE "(favicon\.ico|path : /favicon|container-404\.html|path : /container-404)" || (echo "$line" | grep -q "extension : ico" && printf '%s\n' "${buffer[@]}" | grep -q "path : /favicon") || (echo "$line" | grep -q "extension : html" && printf '%s\n' "${buffer[@]}" | grep -q "path : /container-404"); then
                skip_until_next_request=true
                buffer=() # Clear buffer for favicon and container-404 requests
                continue
            fi
            
            # Skip if we're in a favicon or container-404 request sequence
            if [ "$skip_until_next_request" = true ]; then
                continue
            fi
            
            # Add to buffer instead of writing immediately
            buffer+=("$line")
            
            # If this is a Filter rule entry (end of request sequence), flush buffer
            if echo "$line" | grep -qE "(Filter rule entry|allowed|blocked|Filter rejects)"; then
                printf '%s\n' "${buffer[@]}" >> "$FILTER_LOG"
                buffer=()
            fi
        fi
    done
}

# Start monitoring
echo "$LOG_PREFIX Starting log monitoring..."
extract_filter_logs &

# Keep the script running
wait

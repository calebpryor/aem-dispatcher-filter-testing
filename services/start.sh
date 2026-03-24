#!/bin/bash
# mod_dispatcher.so is not downloaded at container start. Install it only from the
# control panel (download_dispatcher.sh via /api/dispatcher-version). Httpd processes
# wait in wait_httpd.sh until the module file is valid.

CP="${CONTROL_PORT:-59173}"
echo "Dispatcher module: use the control UI at http://127.0.0.1:${CP} (Download & switch module). Apache will start after the .so is installed."

echo "Starting filter file watcher..."
/usr/local/bin/watch_filters.sh &

echo "Starting filter log extractor..."
/usr/local/bin/filter_log_extractor.sh &

/usr/bin/supervisord -j /var/run/supervisor/supervisord.pid

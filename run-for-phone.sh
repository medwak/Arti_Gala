#!/usr/bin/env sh
# Start Arti Gala so phones on the same Wi-Fi (and the Android app) can connect.
exec "$(dirname "$0")/run.sh" --host 0.0.0.0 "$@"

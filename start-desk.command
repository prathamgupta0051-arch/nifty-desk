#!/bin/bash
# Opens the Nifty Positioning Desk. The server itself runs in the background as a
# macOS login service (com.prathamgupta.niftydesk); this restarts it if it is down.
if ! curl -s -o /dev/null --max-time 3 http://127.0.0.1:8765/; then
  launchctl kickstart -k "gui/$(id -u)/com.prathamgupta.niftydesk" 2>/dev/null
  for i in $(seq 1 20); do curl -s -o /dev/null --max-time 2 http://127.0.0.1:8765/ && break; sleep 1; done
fi
open "http://127.0.0.1:8765/"

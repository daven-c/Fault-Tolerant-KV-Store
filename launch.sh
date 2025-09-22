#!/bin/bash

# A script to easily launch multiple Raft server instances.
#
# Usage:
#   ./launch.sh [number_of_servers]
#
# If no number is provided, it defaults to launching 3 servers.

# --- Configuration ---
NUM_SERVERS=${1:-3} # Default to 3 servers if no argument is provided
START_PORT=8000
# This should be the path to your compiled server executable
EXECUTABLE="./build/server"

# --- Pre-launch Sanity Check ---
if [ ! -f "$EXECUTABLE" ]; then
    echo "Error: Server executable not found at '$EXECUTABLE'"
    echo "Please build the project first."
    exit 1
fi

# --- Pre-launch Cleanup ---
echo "Stopping any existing server processes..."
# Use pkill to gracefully kill processes matching the executable path.
# The -f flag matches against the full command line.
pkill -f "$EXECUTABLE"
sleep 1 # Give a moment for processes to terminate cleanly.

# --- Build the list of peer addresses ---
PEERS=""
for (( i=0; i<$NUM_SERVERS; i++ )); do
    PORT=$((START_PORT + i))
    PEERS="$PEERS 127.0.0.1:$PORT"
done
# Trim any leading space from the peers list
PEERS=$(echo "$PEERS" | sed 's/^ *//g')

echo "Starting $NUM_SERVERS servers..."

# --- Launch each server instance in the background ---
for (( i=0; i<$NUM_SERVERS; i++ )); do
    SERVER_ID=$i
    LOG_FILE="server_$SERVER_ID.log"
    
    echo " -> Launching Server $SERVER_ID on port $((START_PORT + i)). Log: $LOG_FILE"
    
    # Launch the server in the background.
    # The command is: ./build/server <server_id> <list_of_all_peers>
    # We redirect both stdout and stderr (2>&1) to the log file.
    # The '&' at the end runs the command in the background.
    $EXECUTABLE $SERVER_ID $PEERS > "$LOG_FILE" 2>&1 &
done

echo ""
echo "All servers launched in the background."
echo "You can monitor logs with a command like: tail -f server_0.log"
echo "To stop all servers, run: pkill -f $EXECUTABLE"

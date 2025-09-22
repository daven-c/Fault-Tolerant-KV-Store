#!/bin/bash

# A script to manage a multi-node Raft server cluster.
#
# Commands:
#   start [num_servers]     - Launches a new cluster with each node in a new terminal. Defaults to 3.
#   start-bg [num_servers]  - Launches a new cluster with nodes running as background processes.
#   stop                    - Stops all running server processes.
#   restart <id> <total>    - Restarts a specific server within a cluster of <total> nodes.
#   reset                   - Removes all logs and AOF files.

# --- Configuration ---
DEFAULT_SERVERS=3
START_PORT=8000
EXECUTABLE="./build/server"
LOG_DIR="server_logs"

# To use a custom terminal, set the TERMINAL_LAUNCHER environment variable.
# See the README.md for examples.
TERMINAL_LAUNCHER=${TERMINAL_LAUNCHER:-""}

# --- Utility Functions ---
build_peer_list() {
    local num_nodes=$1
    local peer_list=""
    for (( i=0; i<$num_nodes; i++ )); do
        local port=$((START_PORT + i))
        peer_list="$peer_list 127.0.0.1:$port"
    done
    echo "$peer_list" | sed 's/^ *//g' # Trim leading space
}

launch_node() {
    local server_id=$1
    local all_peers=$2
    local is_background=$3
    local port=$((START_PORT + server_id))
    local log_file="$LOG_DIR/node_$server_id.log"

    echo " -> Launching Server $server_id on port $port (log: $log_file)..."

    if [ "$is_background" = "true" ]; then
        local command_to_run="$EXECUTABLE $server_id $all_peers"
        # nohup ensures the process isn't killed if the parent terminal closes.
        # Output is redirected to the log file.
        nohup $command_to_run > "$log_file" 2>&1 &
    else
        # Command will show output in terminal AND save it to a log file.
        local full_command="$EXECUTABLE $server_id $all_peers 2>&1 | tee $log_file"

        if [ -n "$TERMINAL_LAUNCHER" ]; then
            # Use custom terminal launcher if set
            local launch_cmd="${TERMINAL_LAUNCHER//'{id}'/$server_id}"
            launch_cmd="${launch_cmd//'{cmd}'/$full_command}"
            launch_cmd="${launch_cmd//'{pwd}'/$(pwd)}"
            eval "$launch_cmd" &
        else
            # Fallback to OS detection
            if [[ "$OSTYPE" == "darwin"* ]]; # macOS
                then osascript -e "tell app \"Terminal\" to do script \"cd '$(pwd)'; echo 'Starting Server $server_id...'; $full_command; exec bash\""
            elif [[ "$OSTYPE" == "linux-gnu"* ]]; then # Linux
                if command -v gnome-terminal &> /dev/null; then
                    gnome-terminal --title="Server $server_id" -- /bin/bash -c "$full_command; echo; echo '--- Server exited. ---'; read"
                elif command -v konsole &> /dev/null; then
                    konsole --new-tab -p "title=Server $server_id" -e /bin/bash -c "$full_command; echo; echo '--- Server exited. ---'; read"
                else
                    echo "Warning: No supported terminal found for Server $server_id. Launching in background."
                    bash -c "$full_command" &
                fi
            else
                 echo "Warning: Unsupported OS for terminal launch. Launching in background."
                 bash -c "$full_command" &
            fi
        fi
    fi
}

# --- Command-line Argument Parsing ---
COMMAND=$1
if [ -z "$COMMAND" ]; then
    echo "Usage: $0 {start|start-bg|stop|restart}"
    echo "Run '$0 start' to launch a default cluster."
    exit 1
fi

# --- Main Logic ---
case "$COMMAND" in
    "start" | "start-bg")
        local is_background=false
        if [ "$COMMAND" = "start-bg" ]; then
            is_background=true
        fi

        NUM_SERVERS=${2:-$DEFAULT_SERVERS}
        echo "Stopping any existing server processes..."
        pkill -f "$EXECUTABLE"
        sleep 1

        if [ ! -f "$EXECUTABLE" ]; then
            echo "Error: Server executable not found at '$EXECUTABLE'. Please build the project."
            exit 1
        fi

        echo "Creating log directory: $LOG_DIR"
        mkdir -p $LOG_DIR

        PEERS=$(build_peer_list $NUM_SERVERS)
        if [ "$is_background" = "true" ]; then
             echo "Starting a new $NUM_SERVERS-node cluster in the background..."
        else
            echo "Starting a new $NUM_SERVERS-node cluster in separate terminals..."
        fi

        for (( i=0; i<$NUM_SERVERS; i++ )); do
            launch_node $i "$PEERS" "$is_background"
        done
        echo "All servers launched."
        ;;

    "stop")
        echo "Stopping all server processes..."
        pkill -f "$EXECUTABLE"
        echo "Done."
        ;;

    "restart")
        SERVER_ID=$2
        TOTAL_SERVERS=$3
        if [ -z "$SERVER_ID" ] || [ -z "$TOTAL_SERVERS" ]; then
            echo "Usage: $0 restart <server_id> <total_servers_in_cluster>"
            exit 1
        fi

        echo "Stopping server $SERVER_ID..."
        pkill -f "$EXECUTABLE $SERVER_ID " # Space prevents killing server 1 when restarting 10
        sleep 1
        
        mkdir -p $LOG_DIR

        PEERS=$(build_peer_list $TOTAL_SERVERS)
        echo "Relaunching server $SERVER_ID into the $TOTAL_SERVERS-node cluster..."
        # Restart always launches in a new terminal for monitoring purposes.
        launch_node $SERVER_ID "$PEERS" false
        echo "Server $SERVER_ID relaunched."
        ;;

    "reset")
        echo "Removing all logs and AOF files..."
        pkill -f "$EXECUTABLE"
        sleep 1
        rm -rf $LOG_DIR
        rm -rf AOFs
        echo "All logs and AOF files removed."
        ;;

    *)
        echo "Unknown command: $COMMAND"
        echo "Usage: $0 {start|start-bg|stop|restart}"
        exit 1
        ;;
esac


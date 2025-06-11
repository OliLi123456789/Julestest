#!/bin/bash

# Script to build and run the Python user strategy in Docker

IMAGE_NAME="python-strategy-env"
CONTAINER_NAME="python-strategy-runner"

# Navigate to the directory where Dockerfile and scripts are located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_ENV_DIR="$SCRIPT_DIR/python" # Assumes Dockerfile, sdk.py, user_strategy.py are in 'python' subdir

echo "Changing directory to: $PYTHON_ENV_DIR"
cd "$PYTHON_ENV_DIR" || { echo "Failed to change directory to $PYTHON_ENV_DIR. Exiting."; exit 1; }

# Ensure a strategy_requirements.txt file exists, create empty if not.
# This prevents Docker's COPY command from failing if the user doesn't have one.
if [ ! -f strategy_requirements.txt ]; then
    echo "strategy_requirements.txt not found. Creating empty file."
    touch strategy_requirements.txt
fi

# Ensure user_strategy.py exists (it's the entrypoint for cde_runner's dynamic import)
if [ ! -f user_strategy.py ]; then
    echo "ERROR: user_strategy.py not found in $PYTHON_ENV_DIR. This file should contain your strategy class."
    if [ -f user_strategy.template.py ]; then
        echo "Found user_strategy.template.py, copying to user_strategy.py to allow build to proceed."
        cp user_strategy.template.py user_strategy.py
    else
        echo "No user_strategy.template.py found either. Please create user_strategy.py with your strategy. Exiting."
        exit 1
    fi
fi

# Ensure cde_runner.py exists (it's the main CMD for the Docker image)
if [ ! -f cde_runner.py ]; then
    echo "ERROR: cde_runner.py not found in $PYTHON_ENV_DIR. This script is essential for running backtests."
    exit 1
fi


# 1. Build the Docker image
echo "Building Docker image '$IMAGE_NAME' from context: $PYTHON_ENV_DIR"
sudo docker build -t "$IMAGE_NAME" .
if [ $? -ne 0 ]; then
    echo "Docker image build failed. Exiting."
    exit 1
fi
echo "Docker image '$IMAGE_NAME' built successfully."

# 2. Run the Docker container
echo "Running Docker container '$CONTAINER_NAME' from image '$IMAGE_NAME'..."

# --- Data Volume Mounting ---
# The CDE expects historical data to be available.
# Mount a host directory containing your CSV data files to /app/historical_data inside the container.
# Replace HOST_SAMPLE_DATA_DIR with the actual path to your data on your host machine.
HOST_SAMPLE_DATA_DIR="$SCRIPT_DIR/sample_data_for_cde"
mkdir -p "$HOST_SAMPLE_DATA_DIR"
DUMMY_AAPL_CSV_PATH="$HOST_SAMPLE_DATA_DIR/AAPL_data.csv"
if [ ! -f "$DUMMY_AAPL_CSV_PATH" ] || [ ! -s "$DUMMY_AAPL_CSV_PATH" ]; then
     echo "Creating dummy AAPL_data.csv for CDE volume mount example at $DUMMY_AAPL_CSV_PATH..."
     echo "Timestamp,Open,High,Low,Close,Volume" > "$DUMMY_AAPL_CSV_PATH"
     echo "2023-01-01T10:00:00Z,150.0,151.0,149.0,150.5,10000" >> "$DUMMY_AAPL_CSV_PATH"
     echo "2023-01-02T10:00:00Z,150.6,152.0,150.0,151.5,12000" >> "$DUMMY_AAPL_CSV_PATH"
     echo "2023-01-03T10:00:00Z,151.6,153.0,151.0,152.5,11000" >> "$DUMMY_AAPL_CSV_PATH"
     echo "2023-01-04T10:00:00Z,152.0,152.8,151.5,151.8,10500" >> "$DUMMY_AAPL_CSV_PATH" # Data used in cde_runner test
     echo "2023-01-05T10:00:00Z,151.8,153.0,151.0,152.9,10800" >> "$DUMMY_AAPL_CSV_PATH"
fi
DUMMY_GOOG_CSV_PATH="$HOST_SAMPLE_DATA_DIR/GOOG_data.csv" # For user_strategy.py sample config
if [ ! -f "$DUMMY_GOOG_CSV_PATH" ] || [ ! -s "$DUMMY_GOOG_CSV_PATH" ]; then
     echo "Creating dummy GOOG_data.csv for CDE volume mount example at $DUMMY_GOOG_CSV_PATH..."
     echo "Timestamp,Open,High,Low,Close,Volume" > "$DUMMY_GOOG_CSV_PATH"
     echo "2023-01-01T10:00:00Z,2500.0,2510.0,2490.0,2505.0,5000" >> "$DUMMY_GOOG_CSV_PATH"
     echo "2023-01-02T10:00:00Z,2506.0,2520.0,2500.0,2515.0,6000" >> "$DUMMY_GOOG_CSV_PATH"
fi

HOST_DATA_PATH_ABS="$(cd "$HOST_SAMPLE_DATA_DIR" && pwd)"
CONTAINER_DATA_PATH="/app/historical_data" # Path inside container, matches SDK default

# --- Backtest Configuration File Mounting ---
# The cde_runner.py script loads its configuration from a YAML file.
# By default, it looks for /app/configs/main_backtest_config.yaml (see cde_runner.py's main block or user_strategy.py's main block).
# You can mount your local 'configs' directory (which should contain your main_backtest_config.yaml)
# into the container at /app/configs.
HOST_CONFIG_DIR="$PYTHON_ENV_DIR/configs" # Path to your local configs dir, relative to PYTHON_ENV_DIR
mkdir -p "$HOST_CONFIG_DIR" # Ensure it exists on host
HOST_CONFIG_DIR_ABS="$(cd "$HOST_CONFIG_DIR" && pwd)"
CONTAINER_CONFIG_DIR_MOUNT_POINT="/app/configs"

# --- Strategy Parameterization ---
# Strategy parameters (e.g., moving average periods, order sizes, thresholds) are primarily configured
# in the YAML configuration file (e.g., main_backtest_config.yaml) within the 'strategy:parameters' section.
# The cde_runner.py script loads this configuration and passes these parameters to your strategy.
#
# To customize strategy parameters for a run:
# 1. Modify the 'strategy:parameters' section of your YAML config file on your host.
# 2. Ensure this config file (e.g., main_backtest_config.yaml) is in the directory you are mounting
#    (e.g., $HOST_CONFIG_DIR_ABS which is mounted to $CONTAINER_CONFIG_DIR_MOUNT_POINT).
#
# Example (if cde_runner.py was modified to accept CLI arguments for config/strategy):
# This is a future enhancement; currently cde_runner.py's __main__ uses a fixed config path
# or loads one that user_strategy.py's __main__ would create.
# CMD_ARGS="--config $CONTAINER_CONFIG_DIR_MOUNT_POINT/main_backtest_config.yaml --strategy_module my_cde_test_strategy --strategy_class TestStrategyForCDERunner"
# For now, cde_runner.py's __main__ will run its own test setup or what user_strategy.py's main would create.
# The CDE_BACKTEST_CONFIG_PATH env var is used by user_strategy.py's old main, and cde_runner's main example uses a local path.
# Ensure the config file specified by CDE_BACKTEST_CONFIG_PATH is the one you want to run.

echo "Attempting to run container..."
echo "Host data directory '$HOST_DATA_PATH_ABS' will be mounted to '$CONTAINER_DATA_PATH' (read-only)."
echo "Host config directory '$HOST_CONFIG_DIR_ABS' will be mounted to '$CONTAINER_CONFIG_DIR_MOUNT_POINT' (read-only)."

# The CMD in the Dockerfile is `python cde_runner.py`.
# cde_runner.py's __main__ block will attempt to load a config.
# We pass CDE_BACKTEST_CONFIG_PATH to guide where it *could* look if it used os.getenv for it.
# The example in cde_runner.py's __main__ uses a hardcoded "cde_runner_main_test_config.yaml".
# For a more flexible CDE, cde_runner.py would parse CLI args for config path & strategy.
sudo docker run --rm --name "$CONTAINER_NAME" \
    -v "$HOST_DATA_PATH_ABS:$CONTAINER_DATA_PATH:ro" \
    -v "$HOST_CONFIG_DIR_ABS:$CONTAINER_CONFIG_DIR_MOUNT_POINT:ro" \
    -e "CDE_HISTORICAL_DATA_PATH=$CONTAINER_DATA_PATH" \
    -e "CDE_BACKTEST_CONFIG_PATH=$CONTAINER_CONFIG_DIR_MOUNT_POINT/main_backtest_config.yaml" \
    "$IMAGE_NAME"
       # No arguments passed to CMD ["python", "cde_runner.py"] yet.
       # It will run cde_runner.py's __main__ block.

if [ $? -ne 0 ]; then
    echo "Docker container run failed."
fi
echo "Docker container '$CONTAINER_NAME' finished."

# Return to original directory from where script was called
cd "$SCRIPT_DIR" || exit
echo "Script finished."

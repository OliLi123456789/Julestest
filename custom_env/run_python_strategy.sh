#!/bin/bash

# Script to build and run the Python user strategy in Docker

IMAGE_NAME="python-strategy-env"
CONTAINER_NAME="python-strategy-runner"

# Navigate to the directory where Dockerfile and scripts are located
# Assuming this script is in 'custom_env' and Dockerfile is in 'custom_env/python'
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_ENV_DIR="$SCRIPT_DIR/python"

echo "Changing directory to: $PYTHON_ENV_DIR"
cd "$PYTHON_ENV_DIR" || { echo "Failed to change directory to $PYTHON_ENV_DIR. Exiting."; exit 1; }

# 1. Build the Docker image
echo "Building Docker image '$IMAGE_NAME'..."
sudo docker build -t "$IMAGE_NAME" .
if [ $? -ne 0 ]; then
    echo "Docker image build failed. Exiting."
    exit 1
fi
echo "Docker image '$IMAGE_NAME' built successfully."

# 2. Run the Docker container
# Use --rm to automatically remove the container when it exits
echo "Running Docker container '$CONTAINER_NAME' from image '$IMAGE_NAME'..."
sudo docker run --rm --name "$CONTAINER_NAME" "$IMAGE_NAME"
if [ $? -ne 0 ]; then
    echo "Docker container run failed."
    # No exit here, to allow potential cleanup
fi
echo "Docker container '$CONTAINER_NAME' finished."

# 3. (Optional) Cleanup: Remove the image
# echo "To remove the Docker image '$IMAGE_NAME', run:"
# echo "docker rmi $IMAGE_NAME"

# Return to original directory (optional, good practice if script is part of larger flow)
# cd "$SCRIPT_DIR"
echo "Script finished. Find Docker logs above."

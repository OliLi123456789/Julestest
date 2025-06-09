# Dockerfile for realtime-ingestor

# --- Builder Stage ---
# Use a specific Go version for reproducibility
FROM golang:1.21-alpine AS builder

# Set working directory
WORKDIR /app

# Copy go.mod and go.sum first to leverage Docker layer caching for dependencies
COPY go.mod go.sum ./
RUN go mod download
RUN go mod verify

# Copy the entire project source code
COPY . .

# Build the application
# -ldflags="-w -s" reduces binary size by stripping debug information
# CGO_ENABLED=0 ensures a statically linked binary without C dependencies (good for alpine)
RUN CGO_ENABLED=0 GOOS=linux go build -a -ldflags="-w -s" -installsuffix cgo -o realtime-ingestor main.go

# --- Final Stage ---
# Use a minimal base image
FROM alpine:latest

# Add ca-certificates for HTTPS calls (e.g., to AWS services like Secrets Manager)
# Add tzdata for timezone information (if your app needs to handle timezones correctly)
RUN apk --no-cache add ca-certificates tzdata

# Set the working directory
WORKDIR /app/

# Copy the pre-built binary file from the builder stage
COPY --from=builder /app/realtime-ingestor .

# (Optional) If you have config files that are part of the image (not recommended for secrets)
# COPY config.json .

# This service doesn't expose a port itself as it's a worker/client.
# If it had an HTTP health check endpoint, you would EXPOSE it.
# EXPOSE 8080

# Command to run the executable
# The binary is now in /app/realtime-ingestor
CMD ["./realtime-ingestor"]

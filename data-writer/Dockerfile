# Dockerfile for data-writer service (Go)

# --- Builder Stage ---
# Use a specific Go version for reproducibility
FROM golang:1.21-alpine AS builder

# Set working directory
WORKDIR /app

# Install Git for fetching private modules if necessary (though direct deps are preferred)
# RUN apk add --no-cache git

# Copy go.mod and go.sum first to leverage Docker layer caching for dependencies
COPY go.mod go.sum ./

# Download Go module dependencies
# If you have private repositories, you might need to configure Git with SSH keys or HTTPS tokens here
# For example:
# ARG GIT_TOKEN
# RUN git config --global url."https://user:${GIT_TOKEN}@github.com".insteadOf "https://github.com"
RUN go mod download
RUN go mod verify


# Copy the entire project source code
# This includes main.go, config/, kafka_consumer/, timestream_writer/
# and potentially a shared 'common/' directory if it's part of the build context.
# If 'common/' is a separate Go module, it should be handled by go.mod replace or be published.
COPY . .
# For this Dockerfile, assume 'common/' (with protos) is at the same level as 'data-writer/'
# and the build context is the parent of both (e.g., 'services/').
# If common is copied, the path in COPY would be e.g. `COPY ../common ./common`
# And Go import paths would be `prop-firm-platform/common/...`
# If common is a module fetched by go mod, then no explicit copy of it here is needed.
# The current go.mod assumes common is available via replace or remote.

# Build the application
# -ldflags="-w -s" reduces binary size by stripping debug information and symbol table.
# CGO_ENABLED=0 ensures a statically linked binary without C dependencies (good for alpine).
RUN CGO_ENABLED=0 GOOS=linux go build -a -ldflags="-w -s" -installsuffix cgo -o data-writer main.go

# --- Final Stage ---
# Use a minimal base image from scratch or alpine
FROM alpine:latest

# Add ca-certificates for HTTPS calls (e.g., to AWS services like Timestream, Secrets Manager)
# Add tzdata for timezone information if your application needs to handle timezones correctly.
RUN apk --no-cache add ca-certificates tzdata

# Set the working directory
WORKDIR /app/

# Copy only the pre-built binary file from the builder stage for a smaller image
COPY --from=builder /app/data-writer .

# This service doesn't expose a port itself as it's a worker consuming from Kafka.
# If it had an HTTP health check endpoint (recommended for production), you would EXPOSE it.
# EXPOSE 8080

# Set user if running as non-root (recommended for production)
# RUN addgroup -S appgroup && adduser -S appuser -G appgroup
# USER appuser

# Command to run the executable
# The binary is now in /app/data-writer
CMD ["./data-writer"]

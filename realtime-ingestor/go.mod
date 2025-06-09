module prop-firm-platform/realtime-ingestor

go 1.21

require (
	github.com/confluentinc/confluent-kafka-go/v2 v2.3.0 // Or latest compatible
	github.com/gorilla/websocket v1.5.1 // Updated to a more recent common version
	google.golang.org/protobuf v1.33.0 // Or latest compatible
	// AWS SDK v2 components would be listed here for secrets manager
	// e.g., github.com/aws/aws-sdk-go-v2/config v1.27.11
	// e.g., github.com/aws/aws-sdk-go-v2/service/secretsmanager v1.21.5
)

// Example of replace directive if using a local common module not yet published
// replace prop-firm-platform/common => ../common

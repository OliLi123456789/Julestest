module prop-firm-platform/data-writer

go 1.21

require (
	github.com/confluentinc/confluent-kafka-go/v2 v2.3.0 // Example version
	google.golang.org/protobuf v1.33.0                 // Example version
	github.com/aws/aws-sdk-go-v2 v1.26.1                 // Example version
	github.com/aws/aws-sdk-go-v2/config v1.27.11         // Example version
	github.com/aws/aws-sdk-go-v2/service/timestreamwrite v1.31.0 // Example version
)

// Replace directive for common protobufs if needed and common is local
// replace prop-firm-platform/common => ../common

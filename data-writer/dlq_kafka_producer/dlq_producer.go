package dlq_kafka_producer

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	// Assuming DLQ config is part of the main config structure
	"prop-firm-platform/data-writer/config"
	"os" // For os.Hostname or a passed-in instanceID
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
)

// DLQMessage structure for messages sent to DLQ
type DLQMessage struct {
	OriginalTopic    string `json:"original_topic"`
	OriginalKey      string `json:"original_key"`
	OriginalPartition int32  `json:"original_partition"`
	OriginalOffset   int64  `json:"original_offset"`
	OriginalValueB64 string `json:"original_value_b64"` // Base64 encoded original value
	FailureReason    string `json:"failure_reason"`
	FailedAt         string `json:"failed_at"`        // UTC timestamp
	ProcessorID      string `json:"processor_id"`     // Identifier for the data-writer instance/pod
}

// DLQProducer handles sending messages to a Dead-Letter Queue.
type DLQProducer struct {
	producer    *kafka.Producer
	dlqTopic    string
	processorID string
}

// NewDLQProducer creates a new DLQ Kafka producer.
// instanceID can be hostname, pod name, or any identifier for the current processor instance.
func NewDLQProducer(cfg config.KafkaDLQConfig, instanceID string) (*DLQProducer, error) {
	if cfg.Topic == "" {
		return nil, fmt.Errorf("DLQ topic is not configured")
	}
	if cfg.BootstrapServers == "" {
		return nil, fmt.Errorf("DLQ Kafka bootstrap servers are not configured")
	}

	kafkaConfigMap := &kafka.ConfigMap{
		"bootstrap.servers": cfg.BootstrapServers,
		"acks":              "all", // Ensure DLQ messages are durably written
		"retries":           5,     // Retry a few times for transient issues
		"linger.ms":         50,    // Allow small batching for DLQ
		// Add other necessary producer configs (security: SASL/SSL if DLQ cluster is secured)
	}
	// Example: Add SASL/SSL from cfg if DLQ kafka needs it and config struct supports it
	// if cfg.SecurityProtocol != "" && ... { ... }

	p, err := kafka.NewProducer(kafkaConfigMap)
	if err != nil {
		return nil, fmt.Errorf("failed to create DLQ Kafka producer: %w", err)
	}
	log.Printf("DLQ Kafka producer created successfully for topic: %s, servers: %s", cfg.Topic, cfg.BootstrapServers)

	// Asynchronous delivery report handler for DLQ producer
	go func() {
		for e := range p.Events() {
			switch ev := e.(type) {
			case *kafka.Message:
				if ev.TopicPartition.Error != nil {
					log.Printf("ERROR: DLQ message delivery failed: %v (Topic: %s, Key: %s)",
						ev.TopicPartition.Error, *ev.TopicPartition.Topic, string(ev.Key))
					// If sending to DLQ fails, this is a critical issue. Might need to log to local disk or escalate.
				} else {
					// log.Printf("DEBUG: DLQ message delivered to %s [%d] at offset %v",
					// 	*ev.TopicPartition.Topic, ev.TopicPartition.Partition, ev.TopicPartition.Offset)
				}
			case kafka.Error:
				log.Printf("ERROR: DLQ Kafka producer error: %v (Code: %d, Fatal: %t)", ev, ev.Code(), ev.IsFatal())
				if ev.IsFatal() {
					// This is very bad, DLQ producer itself is broken.
					log.Println("FATAL: DLQ Kafka producer encountered a fatal error.")
				}
			}
		}
		log.Println("DLQ Kafka producer event channel closed.")
	}()

	var effectiveProcessorID string
	if instanceID != "" {
		effectiveProcessorID = instanceID
	} else {
		hostname, err := os.Hostname()
		if err != nil {
			log.Printf("WARN: Could not get hostname for DLQ processor ID, using default. Error: %v", err)
			effectiveProcessorID = "unknown-data-writer-instance"
		} else {
			effectiveProcessorID = hostname
		}
	}

	return &DLQProducer{producer: p, dlqTopic: cfg.Topic, processorID: effectiveProcessorID}, nil
}

// SendToDLQ sends a failed original Kafka message (from consumer) to the DLQ.
func (dp *DLQProducer) SendToDLQ(originalMsg *kafka.Message, reason string) error {
	if dp == nil || dp.producer == nil {
		log.Println("ERROR: DLQProducer not initialized, cannot send message.")
		return fmt.Errorf("DLQProducer not initialized")
	}
	if originalMsg == nil {
		return fmt.Errorf("cannot send nil original message to DLQ")
	}

	dlqPayload := DLQMessage{
		OriginalTopic:    *originalMsg.TopicPartition.Topic,
		OriginalKey:      string(originalMsg.Key), // Assuming key is string or string-convertible
		OriginalPartition: originalMsg.TopicPartition.Partition,
		OriginalOffset:   int64(originalMsg.TopicPartition.Offset),
		OriginalValueB64: base64.StdEncoding.EncodeToString(originalMsg.Value),
		FailureReason:    reason,
		FailedAt:         time.Now().UTC().Format(time.RFC3339Nano),
		ProcessorID:      dp.processorID,
	}

	payloadBytes, err := json.Marshal(dlqPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal DLQ message (key: %s): %w", string(originalMsg.Key), err)
	}

	deliveryChan := make(chan kafka.Event) // For per-message delivery report if needed, or use global p.Events()
	defer close(deliveryChan)

	err = dp.producer.Produce(&kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &dp.dlqTopic, Partition: kafka.PartitionAny},
		Key:            originalMsg.Key, // Preserve original key for partitioning in DLQ if useful
		Value:          payloadBytes,
		Timestamp:      time.Now(), // Timestamp of DLQ message itself
	}, deliveryChan) // Produce to deliveryChan for this specific message

	if err != nil {
		// This error is for queue full or local client issues.
		log.Printf("ERROR: Failed to enqueue message to DLQ for key %s: %v", string(originalMsg.Key), err)
		return fmt.Errorf("failed to enqueue message to DLQ (key: %s): %w", string(originalMsg.Key), err)
	}

	// Wait for delivery report for this specific message
	// This makes SendToDLQ synchronous for its delivery report, which might be desired for critical DLQ messages.
	// Alternatively, rely on the background p.Events() goroutine and make this fire-and-forget.
	// For DLQ, knowing it was at least accepted by the producer queue is important.
	e := <-deliveryChan
	m := e.(*kafka.Message)
	if m.TopicPartition.Error != nil {
		log.Printf("ERROR: DLQ message (key: %s) delivery confirmation error: %v", string(m.Key), m.TopicPartition.Error)
		return fmt.Errorf("DLQ message (key: %s) delivery confirmation error: %w", string(m.Key), m.TopicPartition.Error)
	}
	// log.Printf("DEBUG: DLQ message for key %s successfully produced to topic %s [%d] at offset %v",
	// 	string(m.Key), *m.TopicPartition.Topic, m.TopicPartition.Partition, m.TopicPartition.Offset)
	return nil
}

// Close flushes pending messages and closes the DLQ producer.
func (dp *DLQProducer) Close() {
	if dp.producer != nil {
		log.Println("DLQ Kafka Producer: Starting to flush pending messages...")
		remaining := dp.producer.Flush(15 * 1000) // 15 seconds timeout
		if remaining > 0 {
			log.Printf("WARN: DLQ Kafka Producer: %d messages still pending delivery after flush timeout.", remaining)
		} else {
			log.Println("DLQ Kafka Producer: All messages flushed successfully.")
		}
		dp.producer.Close()
		log.Println("DLQ Kafka Producer: Closed.")
	}
}

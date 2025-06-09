package kafka_producer

import (
	"fmt"
	"log"
	"time"
	// Ensure your config import path is correct based on your project structure
	"prop-firm-platform/realtime-ingestor/config"
	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"google.golang.org/protobuf/proto"
)

// MarketDataProducer wraps a Kafka producer for market data.
type MarketDataProducer struct {
	producer *kafka.Producer
	cfg      config.KafkaConfig
	// deliveryChan is used to receive delivery reports without blocking Produce call.
	// It's managed by the goroutine started in NewMarketDataProducer.
	// deliveryChan chan kafka.Event
}

// NewMarketDataProducer creates a new Kafka producer instance.
func NewMarketDataProducer(cfg config.KafkaConfig, awsSecrets map[string]string) (*MarketDataProducer, error) {
	kafkaConfigMap := &kafka.ConfigMap{
		"bootstrap.servers": cfg.BootstrapServers,
		"linger.ms":         cfg.ProducerLingerMs,
		"retries":           cfg.ProducerRetries,
		// "acks": "all", // For higher durability, consider "all" or "-1"
		// "compression.type": "snappy", // Or "lz4", "gzip", "zstd"
		// "go.batch.producer": true, // Enable batch producer for better throughput (default true in recent versions)
		// "go.delivery.reports": true, // Ensure delivery reports are enabled for the Events channel
	}

	// Example for SASL_SSL, if configured and secrets were passed in awsSecrets map
	// securityProtocol := awsSecrets["KAFKA_SECURITY_PROTOCOL"] // Assuming keys like KAFKA_SECURITY_PROTOCOL in map
	// saslMechanisms := awsSecrets["KAFKA_SASL_MECHANISMS"]
	// saslUsername := awsSecrets["KAFKA_SASL_USERNAME"]
	// saslPassword := awsSecrets["KAFKA_SASL_PASSWORD"]

	// if securityProtocol == "SASL_SSL" && saslMechanisms != "" && saslUsername != "" && saslPassword != "" {
	// 	(*kafkaConfigMap)["security.protocol"] = securityProtocol
	// 	(*kafkaConfigMap)["sasl.mechanisms"] = saslMechanisms
	// 	(*kafkaConfigMap)["sasl.username"] = saslUsername
	// 	(*kafkaConfigMap)["sasl.password"] = saslPassword
	//  log.Println("Kafka Producer: Configuring SASL_SSL.")
	// }


	p, err := kafka.NewProducer(kafkaConfigMap)
	if err != nil {
		return nil, fmt.Errorf("failed to create Kafka producer: %w", err)
	}

	log.Println("Kafka producer created successfully.")

	// Goroutine to handle delivery reports (acknowledgements from Kafka)
	// This is crucial for understanding if messages are actually making it to Kafka.
	go func() {
		for e := range p.Events() {
			switch ev := e.(type) {
			case *kafka.Message:
				if ev.TopicPartition.Error != nil {
					log.Printf("Kafka delivery failed: Message to %s [%d] @ offset %v: %v",
						*ev.TopicPartition.Topic, ev.TopicPartition.Partition, ev.TopicPartition.Offset, ev.TopicPartition.Error)
					// TODO: Implement DLQ or more robust error handling for failed deliveries.
					// This could involve trying to resend, or writing to a persistent local store/DLQ.
				} else {
					// Successfully delivered message logging can be very verbose. Enable for debugging if needed.
					// log.Printf("DEBUG: Kafka message delivered to %s [%d] at offset %v",
					// 	*ev.TopicPartition.Topic, ev.TopicPartition.Partition, ev.TopicPartition.Offset)
				}
			case kafka.Error:
				// This typically reports broker connection errors or other client-level errors.
				// librdkafka handles many retries internally. If it bubbles up here, it might be serious.
				log.Printf("ERROR: Kafka producer error: %v (Code: %d, Fatal: %t)", ev, ev.Code(), ev.IsFatal())
				if ev.IsFatal() {
					// A fatal error means the producer is likely no longer usable.
					// The application might need to be restarted or enter a degraded state.
					// Consider signaling a shutdown of the application or the producer itself.
					log.Println("FATAL: Kafka producer encountered a fatal error. Application may need to react.")
				}
			default:
				// log.Printf("DEBUG: Kafka producer event ignored: %s", ev)
			}
		}
		log.Println("Kafka producer event channel closed.")
	}()

	return &MarketDataProducer{producer: p, cfg: cfg}, nil
}

// PublishMessage serializes a Protobuf message and publishes it to the appropriate Kafka topic.
// The message key could be the ticker symbol for partitioning.
func (mp *MarketDataProducer) PublishMessage(message proto.Message, key string, messageType string) error {
	if mp.producer == nil {
		return fmt.Errorf("kafka producer is not initialized")
	}

	var topic string
	switch strings.ToLower(messageType) { // Ensure case-insensitivity for msgType
	case "trade":
		topic = mp.cfg.TradeTopic
	case "quote":
		topic = mp.cfg.QuoteTopic
	case "aggregate":
		topic = mp.cfg.AggregateTopic
	default:
		return fmt.Errorf("unknown message type for Kafka publishing: '%s'", messageType)
	}

	if topic == "" {
		return fmt.Errorf("kafka topic for message type '%s' is not configured or empty", messageType)
	}

	payload, err := proto.Marshal(message)
	if err != nil {
		return fmt.Errorf("failed to marshal protobuf message (type: %s, key: %s): %w", messageType, key, err)
	}

	// Produce messages to topic (asynchronously)
	// The delivery report will be handled by the goroutine in NewMarketDataProducer via p.Events()
	// The deliveryChan argument to Produce is for per-message delivery reports if you want to handle them
	// synchronously or in a specific way for that message, separate from the global Events channel.
	// Passing 'nil' means delivery reports go to the main Events channel.
	err = mp.producer.Produce(&kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
		Key:            []byte(key), // Using ticker as key for partitioning
		Value:          payload,
		Timestamp:      time.Now(), // Kafka message timestamp (broker may override with its own if configured)
	}, nil)

	if err != nil {
		// This error is typically if the producer's internal queue is full (rare if librdkafka is working well)
		// or other immediate client-side issues before sending.
		// Most broker communication errors are handled by librdkafka and reported via the Events channel.
		return fmt.Errorf("kafka produce call error (type: %s, key: %s, topic: %s): %w", messageType, key, topic, err)
	}
	// mp.producer.Flush(1 * 1000) // Optional: Flush messages if low throughput and immediate delivery is critical.
	// However, `linger.ms` is generally preferred for batching and better throughput.
	// Flushing too often can degrade performance.
	return nil
}

// Close flushes pending messages and closes the Kafka producer.
// Should be called on graceful shutdown of the service.
func (mp *MarketDataProducer) Close() {
	if mp.producer != nil {
		log.Println("Kafka Producer: Starting to flush pending messages...")
		// Wait for all messages in the producer queue to be delivered.
		// Timeout prevents blocking indefinitely if brokers are unreachable.
		remaining := mp.producer.Flush(15 * 1000) // 15 seconds timeout
		if remaining > 0 {
			log.Printf("WARN: Kafka Producer: %d messages still pending delivery after flush timeout.", remaining)
		} else {
			log.Println("Kafka Producer: All messages flushed successfully.")
		}
		mp.producer.Close() // Closes the producer and its Events channel.
		log.Println("Kafka Producer: Closed.")
	}
}

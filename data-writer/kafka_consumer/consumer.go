package kafka_consumer

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	// Adjust import paths based on your actual project structure
	market_data_pb "prop-firm-platform/common/gen/go/market_data" // Generated Protobuf
	"prop-firm-platform/data-writer/config"
	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"google.golang.org/protobuf/proto"
)

// ConsumedMessage holds a deserialized message and its original Kafka topic details.
type ConsumedMessage struct {
	Topic     string
	Partition int32
	Offset    kafka.Offset
	Key       string
	Value     proto.Message // Deserialized Protobuf message (e.g., *market_data_pb.Trade)
	Timestamp time.Time
}

// KafkaConsumer wraps the confluent-kafka-go consumer.
type KafkaConsumer struct {
	consumer *kafka.Consumer
	cfg      config.KafkaConsumerConfig
	outChan  chan<- ConsumedMessage // Channel to send deserialized messages
	ctx      context.Context
	cancel   context.CancelFunc // To stop the consumer loop internally
}

// NewKafkaConsumer creates and starts a new Kafka consumer.
func NewKafkaConsumer(appCtx context.Context, cfg config.KafkaConsumerConfig, outChan chan<- ConsumedMessage) (*KafkaConsumer, error) {
	kafkaConfigMap := &kafka.ConfigMap{
		"bootstrap.servers":       cfg.BootstrapServers,
		"group.id":                cfg.GroupID,
		"auto.offset.reset":       cfg.AutoOffsetReset,
		"enable.auto.commit":      cfg.EnableAutoCommit,
		"auto.commit.interval.ms": cfg.CommitIntervalMs,
		// "go.application.rebalance.enable": true, // Enable rebalance callback logging
		// "session.timeout.ms": 6000, // Default
		// "heartbeat.interval.ms": 3000, // Default
	}

	// Example: Add SASL/SSL config if needed (ensure cfg has these fields and they are populated)
	// if cfg.SecurityProtocol != "" && cfg.SaslMechanisms != "" && cfg.SaslUsername != "" && cfg.SaslPassword != "" {
	//  (*kafkaConfigMap)["security.protocol"] = cfg.SecurityProtocol
	//  (*kafkaConfigMap)["sasl.mechanisms"] = cfg.SaslMechanisms
	//  (*kafkaConfigMap)["sasl.username"] = cfg.SaslUsername
	//  (*kafkaConfigMap)["sasl.password"] = cfg.SaslPassword
	// }

	consumer, err := kafka.NewConsumer(kafkaConfigMap)
	if err != nil {
		return nil, fmt.Errorf("failed to create Kafka consumer: %w", err)
	}

	err = consumer.SubscribeTopics(cfg.Topics, nil) // TODO: Add rebalance callback if needed
	if err != nil {
		consumer.Close()
		return nil, fmt.Errorf("failed to subscribe to topics %v: %w", cfg.Topics, err)
	}
	log.Printf("Kafka consumer subscribed to topics: %v with group ID: %s", cfg.Topics, cfg.GroupID)

	// Internal context for managing the consumer loop's lifecycle, derived from appCtx
	ctx, cancel := context.WithCancel(appCtx)

	kc := &KafkaConsumer{
		consumer: consumer,
		cfg:      cfg,
		outChan:  outChan,
		ctx:      ctx,
		cancel:   cancel,
	}
	go kc.consumeLoop()
	return kc, nil
}

func (kc *KafkaConsumer) consumeLoop() {
	log.Println("Kafka consumer loop started...")
	defer func() {
		log.Println("Kafka consumer loop stopped.")
		// Consider closing outChan if this consumer is the sole owner/producer for it,
		// but typically outChan is managed by the creator of KafkaConsumer.
	}()

	run := true
	for run {
		select {
		case <-kc.ctx.Done(): // Triggered by kc.Stop() or parent context cancellation
			log.Println("Kafka consumer: Context cancelled, shutting down consume loop.")
			run = false
		default:
			// Poll for messages with a timeout to allow periodic checks of kc.ctx.Done()
			ev := kc.consumer.Poll(1000) // 1 second timeout
			if ev == nil {
				continue // Timeout, no event
			}

			switch e := ev.(type) {
			case *kafka.Message:
				// log.Printf("DEBUG: Received Kafka message from topic %s, partition %d, offset %v, key %s",
				// 	*e.TopicPartition.Topic, e.TopicPartition.Partition, e.TopicPartition.Offset, string(e.Key))

				var deserializedMsg proto.Message
				var errDeserialize error
				topicName := *e.TopicPartition.Topic

				// Determine Protobuf type based on topic name convention
				if strings.Contains(topicName, "trades") {
					trade := &market_data_pb.Trade{}
					errDeserialize = proto.Unmarshal(e.Value, trade)
					deserializedMsg = trade
				} else if strings.Contains(topicName, "quotes") {
					quote := &market_data_pb.Quote{}
					errDeserialize = proto.Unmarshal(e.Value, quote)
					deserializedMsg = quote
				} else if strings.Contains(topicName, "aggregates") {
					agg := &market_data_pb.Aggregate{}
					errDeserialize = proto.Unmarshal(e.Value, agg)
					deserializedMsg = agg
				} else {
					log.Printf("WARN: Unknown topic for deserialization: %s, skipping message", topicName)
					// If not auto-committing, may need to commit this offset to avoid reprocessing.
					if !kc.cfg.EnableAutoCommit {
						kc.commitMessage(e)
					}
					continue
				}

				if errDeserialize != nil {
					log.Printf("ERROR: Failed to deserialize Protobuf message from topic %s: %v. Raw value length: %d. Key: %s",
						topicName, errDeserialize, len(e.Value), string(e.Key))
					// TODO: Send raw e.Value to a Dead Letter Queue (DLQ) for this topic/error type.
					if !kc.cfg.EnableAutoCommit {
						kc.commitMessage(e) // Commit even failed messages to avoid blocking if DLQ is in place
					}
					continue
				}

				// Send successfully deserialized message to the processing channel
				select {
				case kc.outChan <- ConsumedMessage{
					Topic:     topicName,
					Partition: e.TopicPartition.Partition,
					Offset:    e.TopicPartition.Offset,
					Key:       string(e.Key),
					Value:     deserializedMsg,
					Timestamp: e.Timestamp,
				}:
					// If manual commit, this would be where you'd stage the offset for commit
					// AFTER it's successfully written to Timestream.
					// For now, with auto-commit or simplified manual commit, this is fine.
				case <-kc.ctx.Done():
					log.Println("Kafka consumer: Shutdown signaled while sending to outChan.")
					run = false // Ensure loop termination
				}

			case kafka.Error:
				// Errors from librdkafka client
				log.Printf("ERROR: Kafka consumer error: %v (Code: %d, Fatal: %t, Retriable: %t, Abort: %t)",
					e, e.Code(), e.IsFatal(), e.IsRetriable(), e.IsAbort())
				if e.IsFatal() || e.IsAbort() {
					log.Println("FATAL: Kafka consumer encountered a fatal/abort error. Shutting down consume loop.")
					run = false // Exit loop on fatal/abort errors
					// The main application might need to be signalled to restart or handle this.
				}
			case kafka.OffsetsCommitted:
				// Informational event for manual commits.
				// log.Printf("DEBUG: Kafka offsets committed: %v", e)
				if e.Error != nil {
					log.Printf("ERROR: Failed to commit offsets: %v", e.Error)
					// This could be serious if manual commit is used. May require intervention or careful retry.
				}
			case kafka.AssignedPartitions:
				log.Printf("INFO: Kafka partitions assigned: %v", e.Partitions)
				kc.consumer.Assign(e.Partitions)
			case kafka.RevokedPartitions:
				log.Printf("INFO: Kafka partitions revoked: %v", e.Partitions)
				kc.consumer.Unassign()
			default:
				// log.Printf("DEBUG: Kafka consumer event ignored: %s", e)
			}
		}
	}
	log.Println("Kafka consumer: consumeLoop exiting.")
}

// commitMessage manually commits the offset for a given Kafka message.
// Only use if enable.auto.commit is false.
func (kc *KafkaConsumer) commitMessage(m *kafka.Message) {
	if kc.consumer == nil {
		return
	}
	offsets := []kafka.TopicPartition{m.TopicPartition}
	// Increment offset by 1 for commit, as commit is "next message to read"
	offsets[0].Offset++

	committedOffsets, err := kc.consumer.CommitOffsets(offsets)
	if err != nil {
		log.Printf("ERROR: Failed to commit Kafka offset %v: %v", offsets, err)
	} else {
		// log.Printf("DEBUG: Manually committed Kafka offset: %v", committedOffsets)
	}
}

// Stop signals the consumer loop to shut down gracefully.
func (kc *KafkaConsumer) Stop() {
	log.Println("Kafka consumer: Stop requested.")
	kc.cancel() // Trigger context cancellation for the consumeLoop
}

// Close cleans up the Kafka consumer resources. Call after Stop() and loop has exited.
func (kc *KafkaConsumer) Close() {
	if kc.consumer != nil {
		log.Println("Kafka consumer: Closing underlying Kafka consumer client.")
		// If not auto-committing, ensure final offsets are committed before closing.
		// However, robust exactly-once or at-least-once processing requires careful offset management
		// tied to successful downstream processing (e.g., Timestream write).
		// For this example, if auto-commit is false, the last commit might be missed on abrupt shutdown.
		err := kc.consumer.Close()
		if err != nil {
			log.Printf("ERROR: Failed to close Kafka consumer properly: %v", err)
		} else {
			log.Println("Kafka consumer: Underlying Kafka consumer client closed.")
		}
	}
}

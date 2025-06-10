package config

import (
	"os"
	"strconv"
	"strings"
	"time"
	// "prop-firm-platform/common/secrets" // If any secrets needed for this service (e.g. Kafka SASL from Secrets Manager)
	"log"
)

type KafkaConsumerConfig struct {
	BootstrapServers string
	GroupID          string
	Topics           []string // e.g., ["market-data-trades", "market-data-quotes", "market-data-aggregates"]
	AutoOffsetReset  string   // "earliest", "latest"
	EnableAutoCommit bool
	CommitIntervalMs int
	// SecurityProtocol string // Example: "SASL_SSL"
	// SaslMechanisms   string // Example: "PLAIN"
	// SaslUsername     string // Secret name or value
	// SaslPassword     string // Secret name or value
}

type TimestreamConfig struct {
	DatabaseName         string
	TradeTableName       string
	QuoteTableName       string
	AggregateTableName   string
	Region               string
	WriteBatchSize       int           // Number of records per batch (max 100 for Timestream)
	WriteBatchTimeout    time.Duration // Max time to wait before flushing a batch
	MaxRetries           int           // Max retries for Timestream writes
	RetryBaseInterval    time.Duration // Base interval for exponential backoff
	Concurrency          int           // Number of concurrent writers to Timestream (if sharding writes)
}

type KafkaDLQConfig struct {
	BootstrapServers string
	Topic            string
	// Add SASL/SSL configs if DLQ Kafka is different or needs separate auth
}

type Config struct {
	Kafka         KafkaConsumerConfig
	Timestream    TimestreamConfig
	DLQKafka      KafkaDLQConfig // Added DLQ Kafka config
	LogLevel      string
	ShutdownTimeout time.Duration // For graceful shutdown
}

func LoadConfig() (*Config, error) {
	var cfg Config

	// Kafka Consumer Configuration
	cfg.Kafka.BootstrapServers = getEnv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
	cfg.Kafka.GroupID = getEnv("KAFKA_CONSUMER_GROUP_ID", "data-writer-service-group")
	topicsStr := getEnv("KAFKA_CONSUMER_TOPICS", "marketdata.trades,marketdata.quotes,marketdata.aggregates") // Example topics
	cfg.Kafka.Topics = strings.Split(topicsStr, ",")
	cfg.Kafka.AutoOffsetReset = getEnv("KAFKA_AUTO_OFFSET_RESET", "earliest") // Or "latest"
	cfg.Kafka.EnableAutoCommit, _ = strconv.ParseBool(getEnv("KAFKA_ENABLE_AUTO_COMMIT", "true"))
	cfg.Kafka.CommitIntervalMs, _ = strconv.Atoi(getEnv("KAFKA_COMMIT_INTERVAL_MS", "5000")) // Default 5s if auto-commit is on


	// Timestream Configuration
	cfg.Timestream.Region = getEnv("AWS_REGION", "us-east-1") // Should be set in deployment
	cfg.Timestream.DatabaseName = getEnv("TIMESTREAM_DATABASE_NAME", "PropFirmMarketData")
	cfg.Timestream.TradeTableName = getEnv("TIMESTREAM_TRADE_TABLE_NAME", "Trades")
	cfg.Timestream.QuoteTableName = getEnv("TIMESTREAM_QUOTE_TABLE_NAME", "Quotes")
	cfg.Timestream.AggregateTableName = getEnv("TIMESTREAM_AGGREGATE_TABLE_NAME", "Aggregates")

	batchSize, _ := strconv.Atoi(getEnv("TIMESTREAM_WRITE_BATCH_SIZE", "100"))
	if batchSize <= 0 || batchSize > 100 { // Timestream limit
		log.Printf("Warning: TIMESTREAM_WRITE_BATCH_SIZE (%d) out of range (1-100). Defaulting to 100.", batchSize)
		cfg.Timestream.WriteBatchSize = 100
	} else {
		cfg.Timestream.WriteBatchSize = batchSize
	}

	batchTimeoutMs, _ := strconv.Atoi(getEnv("TIMESTREAM_WRITE_BATCH_TIMEOUT_MS", "5000")) // 5 seconds
	cfg.Timestream.WriteBatchTimeout = time.Duration(batchTimeoutMs) * time.Millisecond

	cfg.Timestream.MaxRetries, _ = strconv.Atoi(getEnv("TIMESTREAM_MAX_RETRIES", "5"))
	retryBaseMs, _ := strconv.Atoi(getEnv("TIMESTREAM_RETRY_BASE_INTERVAL_MS", "500")) // 0.5 second
	cfg.Timestream.RetryBaseInterval = time.Duration(retryBaseMs) * time.Millisecond

	cfg.Timestream.Concurrency, _ = strconv.Atoi(getEnv("TIMESTREAM_WRITER_CONCURRENCY", "10")) // Example, number of goroutines writing batches


	// General Configuration
	cfg.LogLevel = getEnv("LOG_LEVEL", "INFO")
	shutdownTimeoutSec, _ := strconv.Atoi(getEnv("SHUTDOWN_TIMEOUT_SECONDS", "30"))
	cfg.ShutdownTimeout = time.Duration(shutdownTimeoutSec) * time.Second


	// Example: Load Kafka SASL credentials from Secrets Manager if names are provided via env vars
	// This requires a secrets manager client, similar to other services.
	// polygonAPIKeySecretName := os.Getenv("POLYGON_API_KEY_SECRET_NAME") // Not used here, but shows pattern
	// if kafkaUserSecretName := getEnv("KAFKA_SASL_USERNAME_SECRET_NAME", ""); kafkaUserSecretName != "" {
	// 	 sm, err := secrets.NewManager(cfg.Timestream.Region) // Assuming common secrets manager
	// 	 if err != nil { return nil, fmt.Errorf("failed to create secrets manager for kafka creds: %w", err)}
	// 	 // cfg.Kafka.SaslUsername, err = sm.GetSecretString(kafkaUserSecretName) // Example
	// 	 if err != nil { return nil, fmt.Errorf("failed to load Kafka username from secret %s: %w", kafkaUserSecretName, err)}
	// } // Similar for password

	// DLQ Kafka Configuration
	cfg.DLQKafka.BootstrapServers = getEnv("DLQ_KAFKA_BOOTSTRAP_SERVERS", cfg.Kafka.BootstrapServers) // Default to same brokers
	cfg.DLQKafka.Topic = getEnv("DLQ_KAFKA_TOPIC", "marketdata.dlq")


	log.Printf("Config Loaded: KafkaBrokers='%s', GroupID='%s', Topics='%v'", cfg.Kafka.BootstrapServers, cfg.Kafka.GroupID, cfg.Kafka.Topics)
	log.Printf("Config Loaded: TimestreamDB='%s', Region='%s', BatchSize=%d", cfg.Timestream.DatabaseName, cfg.Timestream.Region, cfg.Timestream.WriteBatchSize)
	log.Printf("Config Loaded: DLQ KafkaBrokers='%s', DLQ Topic='%s'", cfg.DLQKafka.BootstrapServers, cfg.DLQKafka.Topic)

	return &cfg, nil
}

func getEnv(key, fallback string) string {
	if value, exists := os.LookupEnv(key); exists && value != "" {
		return value
	}
	return fallback
}

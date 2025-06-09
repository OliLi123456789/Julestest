package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	// Adjust import path based on actual project structure for the secrets manager
	"prop-firm-platform/realtime-ingestor/internal/secrets"
)

// PolygonConfig holds configuration specific to Polygon.io connection
type PolygonConfig struct {
	APIKey               string
	WebSocketURL         string
	FeedType             string   // e.g., "trades", "quotes", "aggregates" -> will map to Polygon prefixes like T, Q, A, AM
	AssetClass           string   // e.g., "stocks", "forex", "crypto", "options" -> will map to Polygon path like /stocks, /forex
	RawSymbols           []string // Symbols as provided in config (e.g., "AAPL", "EUR/USD", "X:BTCUSD")
	FormattedParams      string   // Formatted string for Polygon subscription (e.g., "T.AAPL,Q.EUR/USD,AM.X:BTCUSD")
	MaxReconnectAttempts int
	ReconnectInterval    time.Duration
	HandshakeTimeout     time.Duration
	ReadBufferSizeKB     int
	WriteBufferSizeKB    int
	ReconnectBaseInterval time.Duration // e.g., 1s, 2s
	MaxReconnectInterval  time.Duration // e.g., 30s, 60s
	ConnectTimeout        time.Duration // e.g., 10s, 15s
	EnableHeartbeat       bool
	HeartbeatInterval     time.Duration // e.g., 30s
	MainLoopSleepInterval time.Duration // e.g., 5s for the client manager loop in main.go
}

// KafkaConfig holds configuration for Kafka producers
type KafkaConfig struct {
	Brokers        []string
	TradesTopic    string
	QuotesTopic    string
	AggregatesTopic string
	// Add other Kafka producer settings like batch size, linger.ms etc.
}

// KafkaConfig holds configuration for Kafka producers
type KafkaConfig struct {
	BootstrapServers string
	TradeTopic       string
	QuoteTopic       string
	AggregateTopic   string
	// SecurityProtocol string // e.g., "SASL_SSL"
	// SaslMechanisms   string // e.g., "PLAIN"
	// SaslUsername     string // Secret Name or Value
	// SaslPassword     string // Secret Name or Value
	ProducerLingerMs int
	ProducerRetries  int
	// SchemaRegistryURL string // For Schema Registry integration
}


// Config holds the overall service configuration
type Config struct {
	Polygon  PolygonConfig
	Kafka    KafkaConfig
	LogLevel string
	// Other global configs
}

// LoadConfig loads configuration from environment variables and AWS Secrets Manager
func LoadConfig(awsRegion string, polygonAPIKeySecretName string) (*Config, error) {
	var cfg Config

	// --- Secrets ---
	sm, err := secrets.NewManager(awsRegion)
	if err != nil {
		return nil, fmt.Errorf("failed to create secrets manager: %w", err)
	}
	apiKey, err := sm.GetSecretString(polygonAPIKeySecretName)
	if err != nil {
		return nil, fmt.Errorf("failed to load Polygon API key from Secrets Manager ('%s'): %w", polygonAPIKeySecretName, err)
	}
	if apiKey == "" {
		return nil, fmt.Errorf("Polygon API key loaded from Secrets Manager ('%s') is empty", polygonAPIKeySecretName)
	}
	cfg.Polygon.APIKey = apiKey

	// --- Polygon Configuration ---
	cfg.Polygon.WebSocketURL = getEnv("POLYGON_WEBSOCKET_URL", "socket.polygon.io") // No "wss://" prefix, scheme added by client
	cfg.Polygon.FeedType = getEnv("POLYGON_FEED_TYPE", "trades") // E.g., "trades", "quotes", "aggregates"
	cfg.Polygon.AssetClass = getEnv("POLYGON_ASSET_CLASS", "stocks") // E.g., "stocks", "forex", "crypto", "options"

	symbolsStr := getEnv("POLYGON_SYMBOLS", "AAPL,MSFT,GOOG") // Comma-separated
	cfg.Polygon.RawSymbols = strings.Split(symbolsStr, ",")
	if len(cfg.Polygon.RawSymbols) == 0 || symbolsStr == "" {
		return nil, fmt.Errorf("POLYGON_SYMBOLS environment variable must be set and contain at least one symbol")
	}

	// Format symbols for Polygon subscription message
	// Example mapping: "trades" -> "T.", "quotes" -> "Q.", "aggregates" (minute) -> "AM."
	// This might need to be more sophisticated if multiple feed types are subscribed per connection/client instance.
	// For now, assuming one feed type per client instance.
	var tickerPrefix string
	switch strings.ToLower(cfg.Polygon.FeedType) {
	case "trades":
		tickerPrefix = "T."
	case "quotes":
		tickerPrefix = "Q."
	case "aggregates": // Defaulting to minute aggregates as an example
		tickerPrefix = "AM."
	default:
		return nil, fmt.Errorf("unsupported POLYGON_FEED_TYPE: '%s'. Supported: trades, quotes, aggregates", cfg.Polygon.FeedType)
	}

	var paramsBuilder strings.Builder
	for i, symbol := range cfg.Polygon.RawSymbols {
		if i > 0 {
			paramsBuilder.WriteString(",")
		}
		// Polygon symbol formatting can vary by asset class, e.g., "X:BTCUSD" for crypto.
		// The RawSymbols should already be in the correct format expected by Polygon.
		paramsBuilder.WriteString(tickerPrefix)
		paramsBuilder.WriteString(strings.TrimSpace(symbol))
	}
	cfg.Polygon.FormattedParams = paramsBuilder.String()


	cfg.Polygon.MaxReconnectAttempts, _ = strconv.Atoi(getEnv("POLYGON_MAX_RECONNECT_ATTEMPTS", "5"))
	reconnectIntervalSeconds, _ := strconv.Atoi(getEnv("POLYGON_RECONNECT_INTERVAL_SECONDS", "5"))
	cfg.Polygon.ReconnectInterval = time.Duration(reconnectIntervalSeconds) * time.Second

	handshakeTimeoutSeconds, _ := strconv.Atoi(getEnv("POLYGON_HANDSHAKE_TIMEOUT_SECONDS", "10"))
	cfg.Polygon.HandshakeTimeout = time.Duration(handshakeTimeoutSeconds) * time.Second

	cfg.Polygon.ReadBufferSizeKB, _ = strconv.Atoi(getEnv("POLYGON_READ_BUFFER_KB", "1024")) // 1MB default
	cfg.Polygon.WriteBufferSizeKB, _ = strconv.Atoi(getEnv("POLYGON_WRITE_BUFFER_KB", "128")) // 128KB default

	reconnectBaseIntervalSeconds, _ := strconv.Atoi(getEnv("POLYGON_RECONNECT_BASE_INTERVAL_SECONDS", "2"))
	cfg.Polygon.ReconnectBaseInterval = time.Duration(reconnectBaseIntervalSeconds) * time.Second

	maxReconnectIntervalSeconds, _ := strconv.Atoi(getEnv("POLYGON_MAX_RECONNECT_INTERVAL_SECONDS", "30"))
	cfg.Polygon.MaxReconnectInterval = time.Duration(maxReconnectIntervalSeconds) * time.Second

	connectTimeoutSeconds, _ := strconv.Atoi(getEnv("POLYGON_CONNECT_TIMEOUT_SECONDS", "15"))
	cfg.Polygon.ConnectTimeout = time.Duration(connectTimeoutSeconds) * time.Second

	cfg.Polygon.EnableHeartbeat = getEnvBool("POLYGON_ENABLE_HEARTBEAT", true) // Defaulting to true, actual use depends on Polygon's requirements
	heartbeatIntervalSeconds, _ := strconv.Atoi(getEnv("POLYGON_HEARTBEAT_INTERVAL_SECONDS", "30"))
	cfg.Polygon.HeartbeatInterval = time.Duration(heartbeatIntervalSeconds) * time.Second

	mainLoopSleepIntervalSeconds, _ := strconv.Atoi(getEnv("POLYGON_MAIN_LOOP_SLEEP_SECONDS", "5"))
	cfg.Polygon.MainLoopSleepInterval = time.Duration(mainLoopSleepIntervalSeconds) * time.Second


	// --- General Configuration ---
	cfg.LogLevel = getEnv("LOG_LEVEL", "INFO")

	// --- Kafka Configuration (placeholders, will be properly loaded in sub-step 2.4) ---
	// For now, so the struct is complete and client can use it.
	// These will be populated from env vars later.
	cfg.Kafka.BootstrapServers = getEnv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092") // Replace with your Kafka brokers
	cfg.Kafka.TradeTopic = getEnv("KAFKA_TRADE_TOPIC", "marketdata.trades")
	cfg.Kafka.QuoteTopic = getEnv("KAFKA_QUOTE_TOPIC", "marketdata.quotes")
	cfg.Kafka.AggregateTopic = getEnv("KAFKA_AGGREGATE_TOPIC", "marketdata.aggregates")

	cfg.Kafka.ProducerLingerMs, _ = strconv.Atoi(getEnv("KAFKA_PRODUCER_LINGER_MS", "100")) // Default 100ms
	cfg.Kafka.ProducerRetries, _ = strconv.Atoi(getEnv("KAFKA_PRODUCER_RETRIES", "3"))     // Default 3 retries

	// cfg.Kafka.SchemaRegistryURL = getEnv("KAFKA_SCHEMA_REGISTRY_URL", "") // If using schema registry

	// Example for SASL_SSL - assuming username/password might be fetched from Secrets Manager if names are provided
	// cfg.Kafka.SecurityProtocol = getEnv("KAFKA_SECURITY_PROTOCOL", "")
	// cfg.Kafka.SaslMechanisms = getEnv("KAFKA_SASL_MECHANISMS", "")
	// kafkaUserSecretName := getEnv("KAFKA_SASL_USERNAME_SECRET_NAME", "")
	// kafkaPassSecretName := getEnv("KAFKA_SASL_PASSWORD_SECRET_NAME", "")
	// if kafkaUserSecretName != "" {
	// 	  user, err := sm.GetSecretString(kafkaUserSecretName)
	// 	  if err != nil { return nil, fmt.Errorf("failed to load Kafka username from secret %s: %w", kafkaUserSecretName, err) }
	// 	  cfg.Kafka.SaslUsername = user
	// }
	// if kafkaPassSecretName != "" {
	// 	  pass, err := sm.GetSecretString(kafkaPassSecretName)
	// 	  if err != nil { return nil, fmt.Errorf("failed to load Kafka password from secret %s: %w", kafkaPassSecretName, err) }
	// 	  cfg.Kafka.SaslPassword = pass
	// }


	log.Printf("Polygon Config Loaded: URL=%s, AssetClass=%s, FeedType=%s, Subscriptions='%s'\n",
		cfg.Polygon.WebSocketURL, cfg.Polygon.AssetClass, cfg.Polygon.FeedType, cfg.Polygon.FormattedParams)
	log.Printf("Kafka Config Loaded: Brokers=%s, TradeTopic=%s\n", cfg.Kafka.BootstrapServers, cfg.Kafka.TradeTopic)


	return &cfg, nil
}

func getEnv(key, fallback string) string {
	if value, exists := os.LookupEnv(key); exists && value != "" {
		return value
	}
	return fallback
}

func getEnvBool(key string, fallback bool) bool {
	if value, exists := os.LookupEnv(key); exists {
		if strings.ToLower(value) == "true" || value == "1" {
			return true
		}
		if strings.ToLower(value) == "false" || value == "0" {
			return false
		}
	}
	return fallback
}

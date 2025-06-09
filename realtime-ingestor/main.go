package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"math"
	"math/rand"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"prop-firm-platform/realtime-ingestor/config" // Adjust path as per your project structure
	"prop-firm-platform/realtime-ingestor/kafka_producer"
	"prop-firm-platform/realtime-ingestor/polygon"  // Adjust path
	pb "prop-firm-platform/common/gen/go/market_data" // Import for protobuf types
	"google.golang.org/protobuf/proto" // For proto.Message interface
)

func main() {
	// Seed random number generator for jitter
	rand.New(rand.NewSource(time.Now().UnixNano()))
	log.SetFlags(log.LstdFlags | log.Lshortfile) // Add file/line number to logs for easier debugging

	// --- Load Configuration ---
	awsRegion := os.Getenv("AWS_REGION")
	if awsRegion == "" {
		log.Println("AWS_REGION environment variable not set, using default 'us-east-1'")
		awsRegion = "us-east-1" // Default if not set
	}
	polygonAPIKeySecretName := os.Getenv("POLYGON_API_KEY_SECRET_NAME")
	if polygonAPIKeySecretName == "" {
		// For local dev, you might fallback to a direct env var for the key, but not for prod.
		// Or, ensure this is always set in your deployment environment.
		log.Fatal("POLYGON_API_KEY_SECRET_NAME environment variable must be set.")
	}

	cfg, err := config.LoadConfig(awsRegion, polygonAPIKeySecretName)
	if err != nil {
		log.Fatalf("FATAL: Failed to load configuration: %v", err)
	}

	log.Printf("INFO: Configuration loaded. Service will connect to Polygon for AssetClass: '%s', FeedType: '%s', Subscribing to: '%s'",
		cfg.Polygon.AssetClass, cfg.Polygon.FeedType, cfg.Polygon.FormattedParams)

	// --- Setup Channels ---
	// messageProcessingChan is where the Polygon client will send raw messages.
	// Buffer size can be tuned based on expected message volume and processing speed.
	messageProcessingChan := make(chan []byte, cfg.Polygon.ReadBufferSizeKB*2) // Example buffer size

	// Create a cancellable context for graceful shutdown of all goroutines.
	rootCtx, cancelRootCtx := context.WithCancel(context.Background())
	defer cancelRootCtx() // Ensure all paths eventually call cancel

	// Handle OS signals (SIGINT, SIGTERM) for graceful shutdown.
	osSignalChan := make(chan os.Signal, 1)
	signal.Notify(osSignalChan, syscall.SIGINT, syscall.SIGTERM)

	var wg sync.WaitGroup // WaitGroup to ensure all main goroutines finish before exiting

	// Goroutine to listen for OS signals and trigger shutdown
	wg.Add(1)
	go func() {
		defer wg.Done()
		select {
		case sig := <-osSignalChan:
			log.Printf("INFO: Received OS signal: %s. Initiating graceful shutdown...", sig)
			cancelRootCtx()
		case <-rootCtx.Done():
			log.Println("INFO: OS signal handler: Root context cancelled, exiting.")
		}
	}()

	// --- Polygon Client Management Goroutine ---
	// --- Initialize Kafka Producer ---
	// The actual secrets for Kafka SASL/SSL would be fetched in LoadConfig and passed via cfg.Kafka
	// For this example, NewMarketDataProducer might take a map of resolved secrets if needed.
	// We'll pass nil for awsSecrets for now, assuming they are either not used or embedded in cfg.Kafka if fetched.
	kafkaProd, err := kafka_producer.NewMarketDataProducer(cfg.Kafka, nil) // Pass nil for awsSecrets for now
	if err != nil {
		log.Fatalf("FATAL: Failed to create Kafka producer: %v", err)
	}
	defer kafkaProd.Close() // Ensure producer is closed on exit


	// --- Polygon Client Management Goroutine ---
	// This goroutine is responsible for maintaining the WebSocket connection.
	wg.Add(1)
	go func(mainShutdownCancel context.CancelFunc) {
		defer wg.Done()
		var client *polygon.WebSocketClient
		var reconnectAttempts int
		// var lastConnectionAttempt time.Time // Can be used to ensure minimum time between attempts

		for {
			select {
			case <-rootCtx.Done():
				if client != nil && client.IsConnected() {
					log.Println("INFO: Client Manager: Root context done, closing client connection.")
					client.CloseConnection() // Ensure graceful close
				}
				log.Println("INFO: Client Manager: Exiting.")
				return
			default:
				if client == nil || !client.IsConnected() {
					if reconnectAttempts > 0 { // Apply backoff only after the first failed attempt
						// Exponential backoff with jitter
						backoffDuration := time.Duration(math.Pow(2, float64(reconnectAttempts))) * cfg.Polygon.ReconnectBaseInterval
						if backoffDuration > cfg.Polygon.MaxReconnectInterval {
							backoffDuration = cfg.Polygon.MaxReconnectInterval
						}
						// Add jitter: +- 20% of backoffDuration. rand.Intn will panic if arg is <=0.
						var jitter time.Duration
						if int(backoffDuration/5) > 0 {
							jitter = time.Duration(rand.Intn(int(backoffDuration/5))) - (backoffDuration / 10)
						} else {
							jitter = time.Duration(rand.Intn(100)) * time.Millisecond // small jitter if backoff is tiny
						}

						actualSleep := backoffDuration + jitter
						if actualSleep < 100*time.Millisecond { // Ensure minimum sleep
							actualSleep = 100 * time.Millisecond
						}

						log.Printf("INFO: Client Manager: Connection lost/failed. Waiting %v before reconnect attempt #%d (max %d)",
							actualSleep, reconnectAttempts+1, cfg.Polygon.MaxReconnectAttempts)

						select {
						case <-time.After(actualSleep):
							// Continue to reconnect
						case <-rootCtx.Done():
							log.Println("INFO: Client Manager: Root context done during backoff sleep. Exiting.")
							return
						}
					}

					if cfg.Polygon.MaxReconnectAttempts > 0 && reconnectAttempts >= cfg.Polygon.MaxReconnectAttempts {
						log.Printf("ERROR: Client Manager: Max reconnect attempts (%d) reached. Shutting down service.", cfg.Polygon.MaxReconnectAttempts)
						mainShutdownCancel() // Signal other goroutines to stop by cancelling the main context.
						return
					}

					log.Printf("INFO: Client Manager: Attempting to connect (attempt #%d)...", reconnectAttempts+1)
					// lastConnectionAttempt = time.Now() // Useful if you want to ensure minimum time between attempts

					connectCtx, connectCtxCancel := context.WithTimeout(rootCtx, cfg.Polygon.ConnectTimeout)

					currentClient := polygon.NewWebSocketClient(cfg.Polygon, messageProcessingChan)
					err := currentClient.Connect(connectCtx)
					connectCtxCancel()

					if err != nil {
						log.Printf("ERROR: Client Manager: Failed to connect: %v", err)
						reconnectAttempts++
						// currentClient.CloseConnection() // Connect() should ensure conn is nil on failure or closed
						client = nil
						continue
					}

					err = currentClient.Subscribe()
					if err != nil {
						log.Printf("ERROR: Client Manager: Failed to subscribe: %v", err)
						currentClient.CloseConnection()
						reconnectAttempts++
						client = nil
						continue
					}

					log.Println("INFO: Client Manager: Successfully connected and subscribed to Polygon.")
					client = currentClient
					reconnectAttempts = 0

					wg.Add(1) // Add for the ReadMessages goroutine
					go func(activeClient *polygon.WebSocketClient) {
						defer wg.Done()
						log.Println("INFO: Client Manager: Starting Polygon message reader goroutine.")
						activeClient.ReadMessages(rootCtx)
						log.Println("INFO: Client Manager: Polygon message reader goroutine finished.")
					}(client)

					if cfg.Polygon.EnableHeartbeat {
						wg.Add(1) // Add for the StartHeartbeat goroutine
						go func(activeClient *polygon.WebSocketClient) {
							defer wg.Done()
							log.Println("INFO: Client Manager: Starting Polygon heartbeat goroutine.")
							activeClient.StartHeartbeat(rootCtx, cfg.Polygon.HeartbeatInterval)
							log.Println("INFO: Client Manager: Polygon heartbeat goroutine finished.")
						}(client)
					}
				} else {
					// Client is connected. Main loop can sleep.
					// log.Printf("DEBUG: Client Manager: Connection active. Sleeping for %v.", cfg.Polygon.MainLoopSleepInterval)
				}

				select {
				case <-time.After(cfg.Polygon.MainLoopSleepInterval):
				case <-rootCtx.Done():
					// Already handled at the top of the loop, this just makes the sleep interruptible.
				}
			}
		}
	}()

	// --- Message Processing Goroutine ---
	// --- Message Processing Goroutine ---
	wg.Add(1)
	go func(currentKafkaProd *kafka_producer.MarketDataProducer) { // Pass Kafka producer instance
		defer wg.Done()
		log.Println("INFO: Starting message processor goroutine...")
		for {
			select {
			case <-rootCtx.Done():
				log.Println("INFO: Message processor: Root context cancelled. Draining remaining messages...")
				// Drain any remaining messages to avoid blocking Polygon client on shutdown
				for len(messageProcessingChan) > 0 {
					msgBytes := <-messageProcessingChan
					log.Printf("INFO: Message processor (draining): Processing message (raw): %.100s...", string(msgBytes))
					// Add actual processing for drained messages if needed
				}
				log.Println("INFO: Message processor: Exiting.")
				return
			case msgBytes, ok := <-messageProcessingChan:
				if !ok {
					log.Println("INFO: Message processor: messageProcessingChan closed. Polygon client likely stopped or encountered an unrecoverable error reading messages. Exiting processor.")
					cancelRootCtx() // Signal a shutdown if the message source is gone.
					return
				}

				// Parse and Normalize the received message
				// The assetClass from cfg.Polygon.AssetClass is needed by some mapping functions in parser.
				normalizedMessages, msgTypes, err := polygon.ParseAndNormalize(msgBytes, cfg.Polygon.AssetClass)
				if err != nil {
					log.Printf("ERROR: Message processor: Failed to parse/normalize message: %v. Raw: %.200s...", err, string(msgBytes))
					// Optionally, send to a Dead Letter Queue (DLQ) in Kafka here for further inspection
					continue // Continue to next message
				}

				if normalizedMessages == nil || len(normalizedMessages) == 0 {
					// This could be a status message that was handled, or an empty batch.
					// log.Println("DEBUG: Message processor: No data messages returned after normalization (e.g. status message or empty batch).")
					continue
				}

				for i, normalizedMsg := range normalizedMessages {
					msgType := msgTypes[i]
					// Type assertion to proto.Message
					protoMsg, okProto := normalizedMsg.(proto.Message)
					if !okProto {
						log.Printf("WARN: Message processor: Normalized message is not a proto.Message type: %T, skipping Kafka publish.", normalizedMsg)
						continue
					}

					// Determine message key (e.g., ticker)
					var messageKey string
					switch m := protoMsg.(type) {
					case *pb.Trade:
						messageKey = m.Ticker
					case *pb.Quote:
						messageKey = m.Ticker
					case *pb.Aggregate:
						messageKey = m.Ticker
					default:
						log.Printf("WARN: Message processor: Unknown proto message type for key extraction: %T", m)
						messageKey = "unknown_key" // Or skip publishing if key is essential
					}

					if messageKey == "" && msgType != "status" { // Allow empty key for status if we decided to publish them
						log.Printf("WARN: Message processor: Message key (ticker) is empty for type %s, skipping Kafka publish.", msgType)
						continue
					}

					err = currentKafkaProd.PublishMessage(protoMsg, messageKey, msgType)
					if err != nil {
						log.Printf("ERROR: Message processor: Failed to publish message to Kafka (type: %s, key: %s): %v", msgType, messageKey, err)
						// Implement retry or DLQ for Kafka publish failures here if needed beyond producer's internal retries.
					} else {
						// log.Printf("DEBUG: Message processor: Published %s for %s to Kafka.", msgType, messageKey)
					}
				}
			}
		}
	}(kafkaProd) // Pass the kafkaProd instance to the goroutine

	log.Println("INFO: RealtimeIngestor service started. Waiting for signals or context cancellation.")
	// Wait for all main goroutines to complete before exiting main.
	// This happens when rootCtx is cancelled.
	<-rootCtx.Done() // Block main until context is cancelled (e.g., by OS signal or error in critical goroutine)

	log.Println("INFO: Main: Root context cancelled. Waiting for goroutines to complete...")
	// Wait for all essential goroutines to finish.
	// If messageProcessingChan was buffered, the processor might still have work.
	// The client manager should also shut down its reader.
	wg.Wait()
	log.Println("INFO: Main: All goroutines finished. RealtimeIngestor service attempting graceful shutdown.")
}

// Note: The `pb` alias for "prop-firm-platform/common/gen/go/market_data" is already imported at the top.

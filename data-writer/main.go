package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"prop-firm-platform/data-writer/config"
	"prop-firm-platform/data-writer/kafka_consumer"
	"prop-firm-platform/data-writer/timestream_writer"
	// market_data_pb "prop-firm-platform/common/gen/go/market_data" // Not directly used here, but in other packages
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	cfg, err := config.LoadConfig()
	if err != nil {
		log.Fatalf("FATAL: Failed to load configuration: %v", err)
	}

	// Setup structured logging based on config.LogLevel (conceptual, actual setup can vary)
	// For now, default log package is used. A real app would use a leveled, structured logger.
	log.Printf("INFO: Log level set to %s (conceptually)", cfg.LogLevel)


	rootCtx, rootCancel := context.WithCancel(context.Background())
	// defer rootCancel() // Call this explicitly at the end of main for more control over shutdown sequence

	var wg sync.WaitGroup

	// Initialize Timestream Writer
	// The NewTimestreamBatchWriter now starts its own timedFlushLoop goroutine using rootCtx.
	tsWriter, err := timestream_writer.NewTimestreamBatchWriter(rootCtx, cfg.Timestream)
	if err != nil {
		log.Fatalf("FATAL: Failed to create Timestream writer: %v", err)
	}
	// defer tsWriter.Close() // Explicit close sequence implemented below


	// Channel for Kafka messages
	// Buffer size can be tuned. Should be large enough to handle bursts from Kafka consumer
	// while Timestream writer processes batches.
	marketDataChan := make(chan kafka_consumer.ConsumedMessage, cfg.Timestream.WriteBatchSize*cfg.Timestream.Concurrency*2)

	// Start Kafka Consumer Goroutine(s)
	wg.Add(1)
	go func() {
		defer wg.Done()
		log.Println("INFO: Starting Kafka consumer goroutine...")
		// NewKafkaConsumer now starts its own consumeLoop and manages its lifecycle with the passed rootCtx
		consumer, consumerErr := kafka_consumer.NewKafkaConsumer(rootCtx, cfg.Kafka, marketDataChan)
		if consumerErr != nil {
			log.Printf("FATAL: Kafka consumer failed to initialize: %v. Shutting down.", consumerErr)
			rootCancel() // Signal other goroutines to stop
			return
		}
		// defer consumer.Close() // Close is called when rootCtx is done or loop exits within KafkaConsumer

		// Keep this goroutine alive; KafkaConsumer's internal loop handles context cancellation.
		// When rootCtx is cancelled, consumer.Stop() is called, then consumer.Close().
		<-rootCtx.Done() // Wait for cancellation signal
		log.Println("INFO: Kafka consumer goroutine: Notified to stop by root context cancellation.")
		// The consumer.Stop() and consumer.Close() are handled by KafkaConsumer itself when its context is done.
		// However, if NewKafkaConsumer failed, defer consumer.Close() would panic.
		// The KafkaConsumer's internal loop will exit on rootCtx.Done().
		// We need to ensure its Close method is called if it initialized successfully.
		// This is better handled by the KafkaConsumer itself respecting the context for its lifetime.
		// The `defer consumer.Close()` inside NewKafkaConsumer's goroutine is not what we want.
		// Let's assume NewKafkaConsumer's consumeLoop runs until its context (rootCtx) is done,
		// and then it closes itself.
		log.Println("INFO: Kafka consumer goroutine finished.")
	}()

	// Start Timestream Message Processor Goroutine
	wg.Add(1)
	go func() {
		defer wg.Done()
		log.Println("INFO: Starting Timestream message processor goroutine...")
		running := true
		for running {
			select {
			case <-rootCtx.Done():
				log.Println("INFO: Timestream processor: Root context cancelled. Draining channel before exit...")
				// Drain marketDataChan before exiting to allow pending writes.
				// The Kafka consumer should close marketDataChan when it shuts down.
				// This ensures this loop terminates after processing remaining items.
				for msg := range marketDataChan {
					if err := tsWriter.AddRecord(msg); err != nil {
						log.Printf("ERROR: Timestream processor (draining): Failed to add record: %v. Key: %s", err, msg.Key)
					}
				}
				log.Println("INFO: Timestream processor: Exiting after drain attempt (marketDataChan closed or drained).")
				running = false
			case msg, ok := <-marketDataChan:
				if !ok {
					log.Println("INFO: Timestream processor: marketDataChan closed by producer (Kafka consumer). Exiting.")
					// If channel closes, it implies Kafka consumer is done.
					// Signal main shutdown if not already happening (though rootCancel in Kafka consumer init failure handles this).
					if rootCtx.Err() == nil { // Check if not already cancelled
						rootCancel()
					}
					running = false
					continue
				}
				if err := tsWriter.AddRecord(msg); err != nil {
					log.Printf("ERROR: Timestream processor: Failed to add record: %v. Key: %s, Topic: %s", err, msg.Key, msg.Topic)
					// TODO: Implement proper DLQ logic for records that AddRecord fails on.
				}
			}
		}
		log.Println("INFO: Timestream processor goroutine finished.")
	}()


	// Handle OS signals for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Block until a signal is received or context is cancelled by other means (e.g., fatal error in a goroutine)
	select {
	case sig := <-sigChan:
		log.Printf("INFO: Main: Received OS signal: %s. Initiating graceful shutdown...", sig)
	case <-rootCtx.Done():
		log.Println("INFO: Main: Root context cancelled by a goroutine (e.g. fatal init error). Initiating shutdown sequence.")
	}

	// Initiate graceful shutdown
	log.Println("INFO: Main: Initiating shutdown sequence by cancelling root context...")
	rootCancel() // Signal all goroutines to stop

	// Create a timeout for WaitGroup completion
	waitGroupDone := make(chan struct{})
	go func() {
		wg.Wait() // Wait for Kafka consumer and Timestream processor goroutines
		close(waitGroupDone)
	}()

	select {
	case <-waitGroupDone:
		log.Println("INFO: Main: All primary goroutines (Kafka consumer, Timestream processor) finished.")
	case <-time.After(cfg.ShutdownTimeout): // Use configured shutdown timeout
		log.Println("WARN: Main: Graceful shutdown timeout exceeded. Some goroutines might not have finished cleanly.")
	}

	// Perform final cleanup like closing Timestream writer AFTER its dependent goroutines are done (or signaled)
	log.Println("INFO: Main: Closing Timestream writer (includes internal timed flusher stop and final flushes)...")
	tsWriter.Close() // This calls its internal context cancel, waits for its timed flusher, then flushes.

	log.Println("INFO: Main: DataWriter service shut down.")
}

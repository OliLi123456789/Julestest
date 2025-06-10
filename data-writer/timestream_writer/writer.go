package timestream_writer

import (
	"context"
	"errors" // For errors.As
	"fmt"
	"log"
	"math"
	"math/rand"
	"strconv"
	"sync"
	"time"

	// Adjust import paths
	market_data_pb "prop-firm-platform/common/gen/go/market_data"
	"prop-firm-platform/data-writer/config"
	"prop-firm-platform/data-writer/dlq_kafka_producer" // Import for DLQ producer
	"prop-firm-platform/data-writer/kafka_consumer"    // For ConsumedMessage type
	"github.com/confluentinc/confluent-kafka-go/v2/kafka" // For kafka.Message

	"github.com/aws/aws-sdk-go-v2/aws"
	awsgo_cfg "github.com/aws/aws-sdk-go-v2/config" // Renamed to avoid conflict with local config
	"github.com/aws/aws-sdk-go-v2/service/timestreamwrite"
	"github.com/aws/aws-sdk-go-v2/service/timestreamwrite/types"
)

// tableBuffer holds records for a specific Timestream table
type tableBuffer struct {
	tableName        string
	databaseName     string
	records          []types.Record
	originalMessages []*kafka.Message // Store pointer to original Kafka message for DLQ
	lastFlushTime    time.Time
	// bufferMutex is now part of TimestreamBatchWriter, managing access to these buffers if they are map[string]*tableBuffer
}

// TimestreamBatchWriter handles batching and writing records to AWS Timestream.
// It now manages separate buffers for trades, quotes, and aggregates.
type TimestreamBatchWriter struct {
	client          *timestreamwrite.Client
	tsCfg           config.TimestreamConfig
	dlqProducer     *dlq_kafka_producer.DLQProducer // Added DLQ producer field
	tradeBuffer     *tableBuffer
	quoteBuffer     *tableBuffer
	aggregateBuffer *tableBuffer
	bufferMutex     sync.Mutex // Protects access to all buffers
	randSource      *rand.Rand // For jitter in retries, seeded
	ctx             context.Context // Application context for graceful shutdown
	cancel          context.CancelFunc // To stop internal goroutines like timed flusher
	wg              sync.WaitGroup    // To wait for goroutines to finish
}

// NewTimestreamBatchWriter creates a new writer.
func NewTimestreamBatchWriter(appCtx context.Context, cfg config.TimestreamConfig, dlqProd *dlq_kafka_producer.DLQProducer) (*TimestreamBatchWriter, error) {
	awsSDKCfg, err := awsgo_cfg.LoadDefaultConfig(appCtx, awsgo_cfg.WithRegion(cfg.Region))
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}
	client := timestreamwrite.NewFromConfig(awsSDKCfg)

	// Internal context for this writer's goroutines
	ctx, cancel := context.WithCancel(appCtx)

	writer := &TimestreamBatchWriter{
		client:     client,
		tsCfg:      cfg,
		bufferMutex: sync.Mutex{},
		randSource: rand.New(rand.NewSource(time.Now().UnixNano())),
		ctx:        ctx,
		cancel:     cancel,
		dlqProducer: dlqProd, // Store DLQ producer
		tradeBuffer: &tableBuffer{
			records:          make([]types.Record, 0, cfg.WriteBatchSize),
			originalMessages: make([]*kafka.Message, 0, cfg.WriteBatchSize),
			lastFlushTime:    time.Now(),
			tableName:        cfg.TradeTableName,
			databaseName:     cfg.DatabaseName,
		},
		quoteBuffer: &tableBuffer{
			records:          make([]types.Record, 0, cfg.WriteBatchSize),
			originalMessages: make([]*kafka.Message, 0, cfg.WriteBatchSize),
			lastFlushTime:    time.Now(),
			tableName:        cfg.QuoteTableName,
			databaseName:     cfg.DatabaseName,
		},
		aggregateBuffer: &tableBuffer{
			records:          make([]types.Record, 0, cfg.WriteBatchSize),
			originalMessages: make([]*kafka.Message, 0, cfg.WriteBatchSize),
			lastFlushTime:    time.Now(),
			tableName:        cfg.AggregateTableName,
			databaseName:     cfg.DatabaseName,
		},
	}
	writer.wg.Add(1)
	go writer.timedFlushLoop() // Start the timed flusher goroutine

	return writer, nil
}

// AddRecord converts a ConsumedMessage to a Timestream Record and adds it to the appropriate buffer.
// Flushes the specific buffer if it's full.
func (w *TimestreamBatchWriter) AddRecord(consumedMsg kafka_consumer.ConsumedMessage) error {
	w.bufferMutex.Lock()
	defer w.bufferMutex.Unlock()

	var targetBuffer *tableBuffer
	var record types.Record
	var err error // Not used in this section, but good to declare

	// Common dimensions
	dimensions := []types.Dimension{
		{Name: aws.String("ticker"), Value: aws.String(consumedMsg.Key)},
	}

	var timestampNs int64
	var timeStr string

	switch m := consumedMsg.Value.(type) {
	case *market_data_pb.Trade:
		targetBuffer = w.tradeBuffer
		timestampNs = m.GetTimestampNs()
		timeStr = strconv.FormatInt(timestampNs/1e6, 10) // Milliseconds for Timestream time

		tradeDimensions := append([]types.Dimension{}, dimensions...)
		tradeDimensions = append(tradeDimensions, types.Dimension{Name: aws.String("exchange"), Value: aws.String(m.Exchange)})
		if m.Id != "" {
			tradeDimensions = append(tradeDimensions, types.Dimension{Name: aws.String("trade_id"), Value: aws.String(m.Id)})
		}
		record = types.Record{
			Dimensions:       tradeDimensions,
			Time:             aws.String(timeStr),
			TimeUnit:         types.TimeUnitMilliseconds,
			MeasureName:      aws.String("trade_data"), // Common measure name for multi-measure record
			MeasureValueType: types.MeasureValueTypeMulti,
			MeasureValues: []types.MeasureValue{
				{Name: aws.String("price"), Value: aws.String(fmt.Sprintf("%f", m.Price)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("size"), Value: aws.String(strconv.FormatInt(m.Size, 10)), Type: types.MeasureValueTypeBigint},
			},
		}

	case *market_data_pb.Quote:
		targetBuffer = w.quoteBuffer
		timestampNs = m.GetTimestampNs()
		timeStr = strconv.FormatInt(timestampNs/1e6, 10)

		quoteDimensions := append([]types.Dimension{}, dimensions...)
		quoteDimensions = append(quoteDimensions, types.Dimension{Name: aws.String("bid_exchange"), Value: aws.String(m.BidExchange)})
		quoteDimensions = append(quoteDimensions, types.Dimension{Name: aws.String("ask_exchange"), Value: aws.String(m.AskExchange)})

		record = types.Record{
			Dimensions:       quoteDimensions,
			Time:             aws.String(timeStr),
			TimeUnit:         types.TimeUnitMilliseconds,
			MeasureName:      aws.String("quote_data"),
			MeasureValueType: types.MeasureValueTypeMulti,
			MeasureValues: []types.MeasureValue{
				{Name: aws.String("bid_price"), Value: aws.String(fmt.Sprintf("%f", m.BidPrice)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("bid_size"), Value: aws.String(strconv.FormatInt(m.BidSize, 10)), Type: types.MeasureValueTypeBigint},
				{Name: aws.String("ask_price"), Value: aws.String(fmt.Sprintf("%f", m.AskPrice)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("ask_size"), Value: aws.String(strconv.FormatInt(m.AskSize, 10)), Type: types.MeasureValueTypeBigint},
			},
		}

	case *market_data_pb.Aggregate:
		targetBuffer = w.aggregateBuffer
		timestampNs = m.GetStartTimeNs()
		timeStr = strconv.FormatInt(timestampNs/1e6, 10)

		aggDimensions := append([]types.Dimension{}, dimensions...)
		aggDimensions = append(aggDimensions, types.Dimension{Name: aws.String("timeframe"), Value: aws.String(m.Timeframe)})

		record = types.Record{
			Dimensions:       aggDimensions,
			Time:             aws.String(timeStr),
			TimeUnit:         types.TimeUnitMilliseconds,
			MeasureName:      aws.String("aggregate_data"),
			MeasureValueType: types.MeasureValueTypeMulti,
			MeasureValues: []types.MeasureValue{
				{Name: aws.String("open"), Value: aws.String(fmt.Sprintf("%f", m.Open)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("high"), Value: aws.String(fmt.Sprintf("%f", m.High)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("low"), Value: aws.String(fmt.Sprintf("%f", m.Low)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("close"), Value: aws.String(fmt.Sprintf("%f", m.Close)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("volume"), Value: aws.String(strconv.FormatInt(m.Volume, 10)), Type: types.MeasureValueTypeBigint},
				{Name: aws.String("vwap"), Value: aws.String(fmt.Sprintf("%f", m.Vwap)), Type: types.MeasureValueTypeDouble},
				{Name: aws.String("transactions"), Value: aws.String(strconv.FormatInt(m.Transactions, 10)), Type: types.MeasureValueTypeBigint},
			},
		}

	default:
		return fmt.Errorf("unknown message type for Timestream: %T", consumedMsg.Value)
	}

	targetBuffer.records = append(targetBuffer.records, record)
	targetBuffer.originalMessages = append(targetBuffer.originalMessages, consumedMsg.OriginalKafkaMsg) // Store original message

	if len(targetBuffer.records) >= w.tsCfg.WriteBatchSize {
		// This is a bit simplified: flushSpecificBuffer expects context.
		// The AddRecord method should ideally not call flush directly if flush can block for long.
		// Instead, it should signal a flusher goroutine or rely on timed flusher.
		// For now, direct call to illustrate batch fill trigger.
		// A channel based approach for signaling flush might be better.
		// Or, the timed flusher is the only one calling flushSpecificBuffer.
		// Let's assume for now that if batch is full, we flush it here.
		// The context passed would be w.ctx (writer's internal context).
		err = w.flushSpecificBuffer(w.ctx, targetBuffer)
	}
	return err
}

// flushSpecificBuffer sends records from a specific tableBuffer to Timestream.
// This function expects the caller (AddRecord or timedFlushLoop) to handle high-level locking if needed
// for selecting the buffer, but this function will lock for modifying the buffer itself.
func (w *TimestreamBatchWriter) flushSpecificBuffer(ctx context.Context, buffer *tableBuffer) error {
	w.bufferMutex.Lock() // Lock to safely access and modify the shared buffer
	if len(buffer.records) == 0 {
		w.bufferMutex.Unlock()
		// This is a bit tricky; a channel-based approach per buffer might be cleaner.
		// For now, we pass the buffer itself to flush.
		err = w.flushSpecificBuffer(targetBuffer)
	}
	return err
}

// flushSpecificBuffer sends records from a specific tableBuffer to Timestream.
// This function expects the caller (AddRecord or timedFlushLoop) to handle high-level locking if needed
// for selecting the buffer, but this function will lock for modifying the buffer itself.
func (w *TimestreamBatchWriter) flushSpecificBuffer(buffer *tableBuffer) error {
	w.bufferMutex.Lock() // Lock to safely access and modify the shared buffer
	if len(buffer.records) == 0 {
		w.bufferMutex.Unlock()
		return nil
	}

	recordsToFlush := make([]types.Record, len(buffer.records))
	copy(recordsToFlush, buffer.records)
	originalMessagesToFlush := make([]*kafka.Message, len(buffer.originalMessages))
	copy(originalMessagesToFlush, buffer.originalMessages)

	buffer.records = make([]types.Record, 0, w.tsCfg.WriteBatchSize)
	buffer.originalMessages = make([]*kafka.Message, 0, w.tsCfg.WriteBatchSize) // Clear original messages too
	buffer.lastFlushTime = time.Now()
	w.bufferMutex.Unlock() // Unlock before I/O

	input := &timestreamwrite.WriteRecordsInput{
		DatabaseName: aws.String(buffer.databaseName),
		TableName:    aws.String(buffer.tableName),
		Records:      recordsToFlush,
		// CommonAttributes can be defined here if shared across all records in the batch
	}

	var lastErr error
	for attempt := 0; attempt <= w.tsCfg.MaxRetries; attempt++ {
		if attempt > 0 {
			sleepDuration := time.Duration(math.Pow(2, float64(attempt-1))) * w.tsCfg.RetryBaseInterval
			jitter := time.Duration(w.randSource.Int63n(int64(sleepDuration/2))) - (sleepDuration / 4) // Smaller jitter range
			actualSleep := sleepDuration + jitter
			if actualSleep < 100*time.Millisecond {	actualSleep = 100 * time.Millisecond }

			log.Printf("Retrying Timestream write to table %s, attempt %d after %v", buffer.tableName, attempt, actualSleep)
			select {
			case <-time.After(actualSleep):
			case <-w.ctx.Done(): // Check application context for shutdown
				log.Printf("Context cancelled during retry sleep for table %s", buffer.tableName)
				return fmt.Errorf("context cancelled during retry for table %s: %w", buffer.tableName, w.ctx.Err())
			}
		}

		_, err := w.client.WriteRecords(w.ctx, input) // Pass writer's context
		if err != nil {
			lastErr = err
			var rre *types.RejectedRecordsException
			if errors.As(err, &rre) {
				log.Printf("WARN: Timestream WriteRecords rejected %d records to table %s:", len(rre.RejectedRecords), buffer.tableName)
				for _, rr := range rre.RejectedRecords {
					log.Printf("  Rejected Record Index %d: Reason: %s", aws.ToInt32(rr.RecordIndex), aws.ToString(rr.Reason))
				}
				// Consider sending rre.RejectedRecords to a DLQ if they are persistently rejected.
				// For now, retrying the whole batch on RejectedRecordsException.
			} else {
				log.Printf("ERROR: Error writing records to Timestream table %s (attempt %d): %v", buffer.tableName, attempt, err)
			}
			// Check if error is non-retryable (e.g., ValidationException, AccessDeniedException)
			// The AWS SDK v2 has more sophisticated retryers. This is a basic one.
			// If it's a terminal error, break early.
			// For now, we retry on any error up to MaxRetries.
		} else {
			log.Printf("INFO: Successfully wrote %d records to Timestream table %s.", len(recordsToFlush), buffer.tableName)
			return nil // Success
		}
	}

	log.Printf("ERROR: Failed to write %d records to Timestream table %s after %d retries. Last error: %v",
		len(recordsToFlush), buffer.tableName, w.tsCfg.MaxRetries, lastErr)
	// TODO: Implement DLQ logic: send recordsToFlush to a persistent DLQ.
	return fmt.Errorf("failed to write to Timestream table %s after %d retries: %w", buffer.tableName, w.tsCfg.MaxRetries, lastErr)
}

// timedFlushLoop periodically flushes all buffers.
func (w *TimestreamBatchWriter) timedFlushLoop() {
	defer w.wg.Done()
	log.Println("Timestream writer timed flush loop started.")
	ticker := time.NewTicker(w.tsCfg.WriteBatchTimeout / 2) // Flush more frequently than full timeout
	defer ticker.Stop()

	for {
		select {
		case <-w.ctx.Done(): // Use writer's internal context
			log.Println("Timestream writer timed flush loop: Context cancelled, exiting.")
			return
		case <-ticker.C:
			// Need to lock to check buffer lengths and call flush, then unlock.
			// flushSpecificBuffer itself will re-lock for its specific buffer modification.
			// This is slightly inefficient due to multiple locks but safer.
			w.tryFlushBuffer(w.tradeBuffer)
			w.tryFlushBuffer(w.quoteBuffer)
			w.tryFlushBuffer(w.aggregateBuffer)
		}
	}
}

func (w *TimestreamBatchWriter) tryFlushBuffer(buffer *tableBuffer) {
	w.bufferMutex.Lock()
	needsFlush := len(buffer.records) > 0 && time.Since(buffer.lastFlushTime) >= w.tsCfg.WriteBatchTimeout
	if !needsFlush && len(buffer.records) >= w.tsCfg.WriteBatchSize { // Also flush if batch size met, even if timeout not yet
		needsFlush = true
	}
	w.bufferMutex.Unlock() // Unlock before calling flush, which will re-lock its specific part

	if needsFlush {
		log.Printf("Timed flush triggered for table %s.", buffer.tableName)
		if err := w.flushSpecificBuffer(buffer); err != nil {
			log.Printf("ERROR: Error during timed flush for table %s: %v", buffer.tableName, err)
		}
	}
}


// Close flushes any remaining records and signals timed flusher to stop.
func (w *TimestreamBatchWriter) Close() {
	log.Println("Timestream writer: Close called. Signaling timed flusher to stop...")
	w.cancel() // Signal timedFlushLoop to stop by cancelling writer's internal context
	w.wg.Wait() // Wait for timedFlushLoop to exit

	log.Println("Timestream writer: Flushing remaining records before final close...")
	// Final flush of all buffers
	if err := w.flushSpecificBuffer(w.tradeBuffer); err != nil {
		log.Printf("ERROR: Error flushing tradeBuffer during close: %v", err)
	}
	if err := w.flushSpecificBuffer(w.quoteBuffer); err != nil {
		log.Printf("ERROR: Error flushing quoteBuffer during close: %v", err)
	}
	if err := w.flushSpecificBuffer(w.aggregateBuffer); err != nil {
		log.Printf("ERROR: Error flushing aggregateBuffer during close: %v", err)
	}
	log.Println("Timestream writer: All buffers flushed. Closed.")
}

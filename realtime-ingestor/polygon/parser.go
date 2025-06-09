package polygon

import (
	"encoding/json"
	"fmt"
	"log"
	"strings"
	// "time" // Not strictly needed here if timestamps are handled as int64

	// Assuming generated protobufs are in this path, adjust if your project structure differs.
	// The 'pb' alias is conventional.
	pb "prop-firm-platform/common/gen/go/market_data"
)

// GenericPolygonMessage is used to determine the event type `ev` first from a batch.
// Polygon often sends an array of messages: [{"ev":"...", ...}, {"ev":"...", ...}]
type GenericPolygonMessage struct {
	EventType string `json:"ev"`
}

// ParseAndNormalize takes a raw JSON message byte slice from Polygon and converts it
// into a slice of canonical Protobuf messages (as []interface{} to hold different types)
// and a slice of corresponding message types (e.g., "trade", "quote"), or an error.
// It processes each message in a potential array received from Polygon.
func ParseAndNormalize(rawMsg []byte, assetClass string) ([]interface{}, []string, error) {
	var messages []json.RawMessage // Use json.RawMessage to delay full parsing
	err := json.Unmarshal(rawMsg, &messages)

	// If unmarshalling into a slice fails, try unmarshalling as a single object (for some status messages)
	if err != nil {
		var singleMessage json.RawMessage
		if errSingle := json.Unmarshal(rawMsg, &singleMessage); errSingle != nil {
			log.Printf("Parser: Failed to unmarshal as JSON array or single object: %v, raw: %s", err, string(rawMsg))
			return nil, nil, fmt.Errorf("json unmarshal error: not a valid JSON array or object")
		}
		messages = []json.RawMessage{singleMessage} // Treat single message as an array of one
	}

	if len(messages) == 0 {
		// This can happen if Polygon sends an empty array `[]` which is valid JSON.
		// log.Println("Parser: Empty message array received.")
		return nil, nil, nil // No error, but no messages to process
	}

	var normalizedMessages []interface{}
	var messageTypes []string

	for _, singleRawMsg := range messages {
		var genericMsg GenericPolygonMessage
		if err := json.Unmarshal(singleRawMsg, &genericMsg); err != nil {
			log.Printf("Parser: Failed to unmarshal generic part of single message: %v, raw single: %s", err, string(singleRawMsg))
			// Decide: skip this message or return error for whole batch? Skipping for robustness.
			continue
		}

		var normalizedMsg interface{}
		var msgType string
		var parseErr error

		switch strings.ToUpper(genericMsg.EventType) {
		case "T": // Trade
			var polyTrade PolygonTradeMessage
			if err := json.Unmarshal(singleRawMsg, &polyTrade); err != nil {
				parseErr = fmt.Errorf("failed to unmarshal into PolygonTradeMessage: %w. Raw: %s", err, string(singleRawMsg))
			} else {
				trade := &pb.Trade{
					Ticker:       polyTrade.Symbol,
					Price:        polyTrade.Price,
					Size:         polyTrade.Size,
					TimestampNs:  polyTrade.Timestamp * 1e6, // Convert Milliseconds to Nanoseconds
					Exchange:     mapExchangeIDToString(polyTrade.Exchange, assetClass),
					Conditions:   mapConditionCodesToStrings(polyTrade.Conditions, assetClass),
					Tape:         mapTapeIDToString(polyTrade.Tape),
					Id:           polyTrade.TradeID,
				}
				normalizedMsg = trade
				msgType = "trade"
			}

		case "Q": // Quote
			var polyQuote PolygonQuoteMessage
			if err := json.Unmarshal(singleRawMsg, &polyQuote); err != nil {
				parseErr = fmt.Errorf("failed to unmarshal into PolygonQuoteMessage: %w. Raw: %s", err, string(singleRawMsg))
			} else {
				quote := &pb.Quote{
					Ticker:       polyQuote.Symbol,
					BidPrice:     polyQuote.BidPrice,
					BidSize:      polyQuote.BidSize,      // Assuming direct mapping for size, Polygon docs say "in round lots"
					BidExchange:  mapExchangeIDToString(polyQuote.BidExchange, assetClass),
					AskPrice:     polyQuote.AskPrice,
					AskSize:      polyQuote.AskSize,      // Assuming direct mapping
					AskExchange:  mapExchangeIDToString(polyQuote.AskExchange, assetClass),
					TimestampNs:  polyQuote.Timestamp * 1e6, // Convert Milliseconds to Nanoseconds
					Conditions:   mapConditionCodesToStrings(polyQuote.Conditions, assetClass), // Less common for quotes
					Tape:         mapTapeIDToString(polyQuote.Tape),
				}
				normalizedMsg = quote
				msgType = "quote"
			}

		case "A", "AM": // Second Aggregate (A), Minute Aggregate (AM)
			var polyAgg PolygonAggregateMessage
			if err := json.Unmarshal(singleRawMsg, &polyAgg); err != nil {
				parseErr = fmt.Errorf("failed to unmarshal into PolygonAggregateMessage (%s): %w. Raw: %s", genericMsg.EventType, err, string(singleRawMsg))
			} else {
				agg := &pb.Aggregate{
					Ticker:       polyAgg.Symbol,
					Open:         polyAgg.Open,
					High:         polyAgg.High,
					Low:          polyAgg.Low,
					Close:        polyAgg.Close,
					Volume:       polyAgg.Volume,
					Vwap:         polyAgg.VWAP, // Changed to double in proto
					StartTimeNs:  polyAgg.StartTime * 1e6, // Convert Milliseconds to Nanoseconds
					EndTimeNs:    polyAgg.EndTime * 1e6,   // Convert Milliseconds to Nanoseconds
					Timeframe:    getTimeframeFromAggregateEventType(genericMsg.EventType),
					Transactions: polyAgg.Transactions,
				}
				normalizedMsg = agg
				msgType = "aggregate"
			}

		case "STATUS":
			var polyStatus PolygonStatusMessage
			if err := json.Unmarshal(singleRawMsg, &polyStatus); err != nil {
				parseErr = fmt.Errorf("failed to unmarshal into PolygonStatusMessage: %w. Raw: %s", err, string(singleRawMsg))
			} else {
				log.Printf("Parser: Polygon Status Received: [%s] %s", polyStatus.Status, polyStatus.Message)
				// Status messages are not typically forwarded as market data, so normalizedMsg remains nil
				msgType = "status"
			}

		default:
			log.Printf("Parser: Unknown message event type: '%s', Raw: %s", genericMsg.EventType, string(singleRawMsg))
			// Optionally, store unknown messages to a specific "unknown_messages" topic/log for review.
			// For now, we skip adding it to the batch of successfully parsed messages.
			continue // Skip this message
		}

		if parseErr != nil {
			log.Printf("Parser: Error for event type '%s': %v", genericMsg.EventType, parseErr)
			// Decide: skip this message or return error for whole batch? Skipping for robustness.
			continue
		}

		if normalizedMsg != nil {
			normalizedMessages = append(normalizedMessages, normalizedMsg)
			messageTypes = append(messageTypes, msgType)
		}
	}

	if len(normalizedMessages) == 0 && len(messages) > 0 {
		// All messages in the batch were either status, unknown, or failed to parse
		// but we don't want to return an error if some were just status messages.
		// If there were actual parse errors, they were logged.
		return nil, nil, nil
	}

	return normalizedMessages, messageTypes, nil
}

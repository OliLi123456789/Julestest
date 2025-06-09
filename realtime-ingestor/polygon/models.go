package polygon

import "fmt"

// PolygonStatusMessage represents status messages from Polygon.io
// Example: {"ev":"status","status":"connected","message":"Connected successfully"}
// Example: {"ev":"status","status":"auth_success","message":"authenticated"}
// Example: {"ev":"status","status":"success","message":"subscribed to: T.AAPL"}
type PolygonStatusMessage struct {
	EventType string `json:"ev"`      // e.g., "status"
	Status    string `json:"status"`  // e.g., "connected", "auth_success", "success"
	Message   string `json:"message"` // e.g., "Connected successfully"
}

// PolygonTradeMessage represents a trade message from Polygon.io (example for stocks)
// Docs: https://polygon.io/docs/stocks/ws_stocks_trades
// Example: {"ev":"T","sym":"AAPL","i":"12345","x":4,"p":150.25,"s":100,"t":1672531200000,"c":[14,37],"z":1}
type PolygonTradeMessage struct {
	EventType  string  `json:"ev"` // "T" for trades
	Symbol     string  `json:"sym"`
	TradeID    string  `json:"i"`      // Trade ID (Polygon's ID, can be non-unique for corrections sometimes, but usually unique for new trades)
	Exchange   int32   `json:"x"`      // Exchange ID (integer)
	Price      float64 `json:"p"`
	Size       int64   `json:"s"`
	Timestamp  int64   `json:"t"`      // Unix Millisecond epoch timestamp
	Conditions []int32 `json:"c"`      // Condition codes (integers)
	Tape       int32   `json:"z"`      // Tape ID (integer)
	// Correction int32   `json:"corr"` // Correction indicator (optional)
	// SequenceNumber int64 `json:"seq"` // Sequence number (if available on higher tiers)
}

// PolygonQuoteMessage represents a quote message from Polygon.io (example for stocks NBBO)
// Docs: https://polygon.io/docs/stocks/ws_stocks_quotes
// Example: {"ev":"Q","sym":"AAPL","bx":4,"bp":150.24,"bs":10,"ax":2,"ap":150.26,"as":15,"t":1672531200001,"c":[14],"z":1}
type PolygonQuoteMessage struct {
	EventType   string  `json:"ev"` // "Q" for quotes
	Symbol      string  `json:"sym"`
	BidExchange int32   `json:"bx"` // Bid Exchange ID
	BidPrice    float64 `json:"bp"`
	BidSize     int64   `json:"bs"` // Typically in round lots (e.g., 1 = 100 shares)
	AskExchange int32   `json:"ax"` // Ask Exchange ID
	AskPrice    float64 `json:"ap"`
	AskSize     int64   `json:"as"` // Typically in round lots
	Timestamp   int64   `json:"t"`  // Unix Millisecond epoch timestamp
	Conditions  []int32 `json:"c"`  // Condition codes (integers) - less common for quotes but possible
	Tape        int32   `json:"z"`  // Tape ID
	// SequenceNumber int64 `json:"seq"` // Sequence number
}

// PolygonAggregateMessage represents an aggregate message (example for minute bars for stocks)
// Docs: https://polygon.io/docs/stocks/ws_stocks_aggregates_minute
// Example: {"ev":"AM","sym":"AAPL","v":12500,"av":125000,"op":150.20,"vw":150.225,"o":150.20,"c":150.25,"h":150.30,"l":150.15,"a":150.225,"s":1672531200000,"e":1672531259999,"otc":false, "n":100}
type PolygonAggregateMessage struct {
	EventType      string  `json:"ev"`  // "AM" for minute aggregates, "A" for second aggregates
	Symbol         string  `json:"sym"`
	Volume         int64   `json:"v"`   // Volume for the period
	AccumulatedVol int64   `json:"av"`  // Accumulated volume for the day (optional)
	OfficialOpen   float64 `json:"op"`  // Official open price for the day (optional)
	VWAP           float64 `json:"vw"`  // VWAP for the period
	Open           float64 `json:"o"`
	Close          float64 `json:"c"`
	High           float64 `json:"h"`
	Low            float64 `json:"l"`
	StartTime      int64   `json:"s"`   // Unix Millisecond epoch timestamp for start of agg window
	EndTime        int64   `json:"e"`   // Unix Millisecond epoch timestamp for end of agg window
	Transactions   int64   `json:"n"`   // Number of trades in aggregate (optional)
	IsOTC          bool    `json:"otc"` // If the aggregate is for an OTC ticker (optional)
}

// --- Mapping functions (Conceptual placeholders - require detailed Polygon documentation) ---

// mapExchangeIDToString converts Polygon integer exchange ID to a string representation.
// This would use a comprehensive mapping table based on Polygon.io documentation.
func mapExchangeIDToString(id int32, assetClass string) string {
	// Example (very simplified, needs actual mappings from Polygon docs):
	// For stocks: https://polygon.io/docs/stocks/get_v3_reference_exchanges
	// For crypto: https://polygon.io/docs/crypto/get_v3_reference_exchanges
	// For forex: Usually not applicable or might indicate bank/source.
	// Needs to be context-aware (stocks, options, forex, crypto have different codes)
	return fmt.Sprintf("%d", id) // Placeholder: just convert int to string
}

// mapConditionCodesToStrings converts Polygon integer condition codes to a list of strings.
// This requires a detailed mapping table from Polygon.io documentation for each asset class.
// For stocks: https://polygon.io/docs/stocks/ws_stocks_trades (search for "Conditions Mapping")
func mapConditionCodesToStrings(codes []int32, assetClass string) []string {
	if len(codes) == 0 {
		return nil
	}
	strCodes := make([]string, len(codes))
	for i, code := range codes {
		// Placeholder: In a real scenario, lookup 'code' in a map for its string meaning.
		strCodes[i] = fmt.Sprintf("Cond%d", code)
	}
	return strCodes
}

// mapTapeIDToString converts Polygon integer tape ID to a string representation (for US stocks).
// See: https://polygon.io/docs/stocks/ws_stocks_trades (search for "Tape ID")
func mapTapeIDToString(id int32) string {
	switch id {
	case 1:
		return "CTA_A" // NYSE
	case 2:
		return "CTA_B" // NYSE Arca, NYSE American, etc.
	case 3:
		return "UTP_C" // Nasdaq
	default:
		return fmt.Sprintf("Tape%d", id) // Unknown or other
	}
}

// getTimeframeFromAggregateEventType returns a standardized timeframe string based on Polygon event type.
func getTimeframeFromAggregateEventType(ev string) string {
	switch ev {
	case "AM":
		return "M1" // 1 Minute
	case "A":
		return "S1" // 1 Second
		// Add cases for "A5" (5s), "A30" (30s) etc. if Polygon uses them or if you subscribe to those.
		// Daily "D", Weekly "W", Monthly "M" usually come from REST APIs, not real-time aggregates.
	default:
		return "UNKNOWN"
	}
}

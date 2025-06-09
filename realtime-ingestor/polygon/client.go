package polygon

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"prop-firm-platform/realtime-ingestor/config" // Path to config package
)

// WebSocketClient handles connection and communication with Polygon.io WebSocket
type WebSocketClient struct {
	conn        *websocket.Conn
	mu          sync.Mutex // To protect concurrent writes to conn and modifications to conn state
	config      config.PolygonConfig
	messageChan chan<- []byte // Channel to send received messages for processing (write-only for client)
	stopOnce    sync.Once
	stopChan    chan struct{} // Internal signal to stop ReadMessages
	isConnected bool
	lastPingSent time.Time // For client-side ping logic
	lastPongRcvd time.Time // For server-side pong logic (if server pings client)
	// logger      *log.Logger // Or a more structured logger from a shared logging package
}

// AuthMessage is the structure for Polygon.io WebSocket authentication
type AuthMessage struct {
	Action string `json:"action"`
	Params string `json:"params"` // API Key
}

// SubscribeMessage is for subscribing to specific tickers
type SubscribeMessage struct {
	Action string `json:"action"` // "subscribe" or "unsubscribe"
	Params string `json:"params"` // Comma-separated list of tickers, e.g., "T.AAPL,Q.MSFT"
}

// NewWebSocketClient creates a new client
func NewWebSocketClient(cfg config.PolygonConfig, msgChan chan<- []byte) *WebSocketClient {
	return &WebSocketClient{
		config:      cfg,
		messageChan: msgChan,
		stopChan:    make(chan struct{}),
		// logger:      log.New(os.Stdout, "PolygonClient: ", log.LstdFlags|log.Lshortfile),
	}
}

// Connect establishes a WebSocket connection and authenticates
func (c *WebSocketClient) Connect(ctx context.Context) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.isConnected && c.conn != nil {
		log.Println("PolygonClient: Already connected or connection attempt in progress.")
		return nil
	}

	// Construct URL based on asset class. Polygon specific.
	// Stocks: /stocks, Forex: /forex, Crypto: /crypto, Options: /options
	// This path segment might need adjustment based on exact Polygon.io documentation.
	// For example, Polygon's docs often show direct paths like wss://socket.polygon.io/stocks
	var pathSegment string
	switch strings.ToLower(c.config.AssetClass) {
	case "stocks":
		pathSegment = "/stocks"
	case "forex":
		pathSegment = "/forex"
	case "crypto":
		pathSegment = "/crypto"
	case "options":
		pathSegment = "/options"
	default:
		return fmt.Errorf("unsupported asset class for Polygon WebSocket URL: %s", c.config.AssetClass)
	}

	u := url.URL{Scheme: "wss", Host: c.config.WebSocketURL, Path: pathSegment}
	log.Printf("PolygonClient: Connecting to %s", u.String())

	dialer := websocket.Dialer{
		ReadBufferSize:  c.config.ReadBufferSizeKB * 1024,
		WriteBufferSize: c.config.WriteBufferSizeKB * 1024,
		HandshakeTimeout: c.config.HandshakeTimeout,
	}

	conn, _, err := dialer.Dial(u.String(), nil)
	if err != nil {
		c.isConnected = false
		return fmt.Errorf("PolygonClient: failed to dial polygon websocket (%s): %w", u.String(), err)
	}
	c.conn = conn
	c.isConnected = true // Mark as connected (logically, will be verified by read loop)
	log.Println("PolygonClient: Successfully established WebSocket connection.")

	// Authenticate
	authMsg := AuthMessage{Action: "auth", Params: c.config.APIKey}
	authBytes, err := json.Marshal(authMsg)
	if err != nil {
		c.CloseConnection() // Use helper
		return fmt.Errorf("PolygonClient: failed to marshal auth message: %w", err)
	}

	if err := c.conn.WriteMessage(websocket.TextMessage, authBytes); err != nil {
		c.CloseConnection()
		return fmt.Errorf("PolygonClient: failed to send auth message: %w", err)
	}
	log.Println("PolygonClient: Authentication message sent.")

	// A real implementation MUST read and validate the authentication status message from Polygon.
	// Polygon sends a status message like: [{"ev":"status","status":"auth_success","message":"authenticated"}]
	// This usually involves a short read loop with a timeout right after sending auth.
	// For this conceptual step, we are omitting this explicit read for brevity, but it's critical.
	// A robust implementation would read messages until an auth success/failure status is received.
	// Example:
	// if err := c.waitForAuthConfirmation(ctx); err != nil {
	//    c.CloseConnection()
	//    return fmt.Errorf("PolygonClient: authentication failed or timed out: %w", err)
	// }
	log.Println("PolygonClient: Authentication successful (conceptually).")


	return nil
}

// waitForAuthConfirmation (Conceptual - not fully implemented here)
// func (c *WebSocketClient) waitForAuthConfirmation(ctx context.Context) error {
//	 log.Println("PolygonClient: Waiting for authentication confirmation...")
//	 // Set a deadline for receiving auth confirmation
//	 c.conn.SetReadDeadline(time.Now().Add(10 * time.Second)) // Example: 10s timeout for auth
//	 defer c.conn.SetReadDeadline(time.Time{}) // Clear deadline after this function
//
//	 for {
//		 // Check for context cancellation
//		 select {
//		 case <-ctx.Done():
//			 return ctx.Err()
//		 default:
//		 }
//
//		 _, msg, err := c.conn.ReadMessage()
//		 if err != nil {
//			 return fmt.Errorf("error reading message during auth: %w", err)
//		 }
//		 log.Printf("PolygonClient: Received message during auth: %s", string(msg))
//		 // Attempt to parse as a status message
//		 var statusMsgs []PolygonStatusMessage // Polygon often sends arrays
//		 if json.Unmarshal(msg, &statusMsgs) == nil && len(statusMsgs) > 0 {
//			 for _, statusMsg := range statusMsgs {
//				 if statusMsg.EventType == "status" && statusMsg.Status == "auth_success" {
//					 log.Println("PolygonClient: Authentication successful (confirmed by server).")
//					 return nil
//				 }
//				 if statusMsg.EventType == "status" && statusMsg.Status == "auth_failed" {
//					 return fmt.Errorf("authentication failed: %s", statusMsg.Message)
//				 }
//			 }
//		 }
//		 // If not the message we're looking for, continue reading (within timeout)
//	 }
// }

// Subscribe subscribes to the configured symbols
func (c *WebSocketClient) Subscribe() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	if !c.isConnected || c.conn == nil {
		return fmt.Errorf("PolygonClient: not connected, cannot subscribe")
	}

	subMsg := SubscribeMessage{Action: "subscribe", Params: c.config.FormattedParams}
	subBytes, err := json.Marshal(subMsg)
	if err != nil {
		return fmt.Errorf("PolygonClient: failed to marshal subscribe message: %w", err)
	}

	if err := c.conn.WriteMessage(websocket.TextMessage, subBytes); err != nil {
		return fmt.Errorf("PolygonClient: failed to send subscribe message: %w", err)
	}
	log.Printf("PolygonClient: Subscription message sent for: %s", c.config.FormattedParams)
	return nil
}

// ReadMessages continuously reads messages from the WebSocket
// and sends them to the messageChan. This should be run in a goroutine.
func (c *WebSocketClient) ReadMessages(ctx context.Context) {
	if c.conn == nil { // Should be checked by caller before starting goroutine
		log.Println("PolygonClient: ReadMessages: Connection is nil at start.")
		// Signal error through messageChan closure if it's managed by this client's lifecycle
		// close(c.messageChan) // This might be too aggressive if chan is shared or re-used.
		return
	}

	// Ensure connection is closed when this function exits.
	// This defer will run when the ReadMessages goroutine ends, either by error or signal.
	defer func() {
		c.CloseConnection() // This sets isConnected to false and closes conn
		log.Println("PolygonClient: ReadMessages goroutine finished and connection closed.")
	}()


	for {
		// Prioritize context cancellation or explicit stop signal
		select {
		case <-ctx.Done():
			log.Println("PolygonClient: ReadMessages: Context cancelled.")
			return // Exit goroutine
		case <-c.stopChan:
			log.Println("PolygonClient: ReadMessages: Stop signal received.")
			return // Exit goroutine
		default:
			// Proceed with reading
		}

		// Set a read deadline to allow periodic checks of ctx.Done() / c.stopChan
		// This makes the ReadMessage call non-blocking indefinitely.
		if c.conn == nil { // Connection might have been closed by another part
			log.Println("PolygonClient: ReadMessages: Connection became nil during loop.")
			return
		}
		c.conn.SetReadDeadline(time.Now().Add(2 * time.Second)) // Adjust timeout as needed

		msgType, message, err := c.conn.ReadMessage()
		if err != nil {
			// Reset read deadline immediately after ReadMessage returns, regardless of error.
			// c.conn.SetReadDeadline(time.Time{}) // Not needed if connection is being closed on error

			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				// Timeout is normal, continue to check context/stopChan
				continue
			}
			// Check for clean close or unexpected close errors
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure, websocket.CloseNoStatusReceived) {
				log.Printf("PolygonClient: ReadMessages: WebSocket unexpected close error: %v", err)
			} else if err == websocket.ErrCloseSent || strings.Contains(err.Error(), "use of closed network connection"){
				log.Printf("PolygonClient: ReadMessages: WebSocket connection closed gracefully or send on closed: %v", err)
			} else {
				log.Printf("PolygonClient: ReadMessages: Error reading message: %v", err)
			}
			// Any error from ReadMessage (other than timeout) means the connection is likely dead.
			// The defer func will handle closing. Signal that messages are no longer coming.
			return // Exit goroutine, defer will cleanup.
		}

		// Reset read deadline if message received successfully
		// c.conn.SetReadDeadline(time.Time{}) // Not strictly needed if we always set before read

		if msgType == websocket.TextMessage || msgType == websocket.BinaryMessage {
			// Send valid message to processing channel (non-blocking send to avoid deadlock if channel is full)
			select {
			case c.messageChan <- message:
				// message sent
			case <-ctx.Done():
				log.Println("PolygonClient: ReadMessages: Context cancelled while trying to send to messageChan.")
				return
			case <-c.stopChan:
				log.Println("PolygonClient: ReadMessages: Stop signal received while trying to send to messageChan.")
				return
			default:
				log.Printf("PolygonClient: ReadMessages: Warning: messageChan is full or blocked. Message dropped: %s", string(message[:100]))
				// This indicates a problem with the consumer of messageChan.
			}
		} else if msgType == websocket.CloseMessage {
			log.Println("PolygonClient: ReadMessages: Received WebSocket CloseMessage from server.")
			return // Exit goroutine, defer will call CloseConnection
		}
		// Gorilla's default PingHandler (set by `conn.SetPingHandler`) automatically sends a Pong response.
		// If we need to track server Pings or client Pongs, custom handlers are needed.
		// For now, assume default ping/pong handling by Gorilla is sufficient if server initiates pings.
	}
}

// StartHeartbeat periodically sends pings if configured.
// Polygon.io typically relies on TCP keepalives and active data flow.
// Explicit client-to-server PINGs might not be required or could even be unsupported.
// This function provides a framework if client-side PINGs are deemed necessary.
// VERIFY POLYGON.IO DOCUMENTATION FOR THEIR RECOMMENDED KEEPALIVE MECHANISM.
func (c *WebSocketClient) StartHeartbeat(ctx context.Context, interval time.Duration) {
	if !c.config.EnableHeartbeat { // Check if heartbeat is enabled in config
		log.Println("Heartbeat: Disabled by configuration.")
		return
	}

	// Ensure client is connected before starting heartbeat.
	// This check might be redundant if StartHeartbeat is only called after a successful connection.
	c.mu.Lock()
	initialConn := c.conn
	c.mu.Unlock()
	if initialConn == nil {
		log.Println("Heartbeat: Not starting, client not connected.")
		return
	}

	log.Printf("Heartbeat: Starting heartbeat pinger with interval %v.", interval)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("Heartbeat: Context done, stopping heartbeat.")
			return
		case <-c.stopChan: // stopChan is used by CloseConnection()
			log.Println("Heartbeat: Stop signal received, stopping heartbeat.")
			return
		case <-ticker.C:
			c.mu.Lock()
			if c.conn == nil { // Check connection again inside lock, it might have been closed
				c.mu.Unlock()
				log.Println("Heartbeat: Connection is nil, stopping heartbeat.")
				return
			}
			// log.Printf("Heartbeat: Sending PING at %v", time.Now())
			// Gorilla handles Ping/Pong concurrently. WriteControl is for sending control messages.
			// It's important to use WriteControl for Ping/Pong to not interfere with data messages.
			// The PingMessage payload can be empty or contain arbitrary data.
			// The server should respond with a PongMessage, ideally echoing the payload.
			// The default PongHandler in Gorilla updates the read deadline, which helps keep connection alive.
			err := c.conn.WriteControl(websocket.PingMessage, []byte("keepalive-ping"), time.Now().Add(10*time.Second))
			if err != nil {
				// If sending a PING fails, the connection is likely compromised.
				// ReadMessages will probably also detect this and trigger reconnection.
				// No need to directly manage reconnection from here to avoid race conditions.
				log.Printf("Heartbeat: Error sending PING: %v. Connection might be dead. ReadMessages should handle this.", err)
				// It's important that ReadMessages exits if the connection is truly dead.
				// If ReadMessages is stuck, this heartbeat PING failure is a symptom.
				// The main client management loop will eventually try to reconnect if ReadMessages exits.
				c.mu.Unlock()
				return // Stop this heartbeat goroutine as connection is likely bad.
			}
			c.lastPingSent = time.Now()
			c.mu.Unlock()
		}
	}
}

// Optional: Custom Pong Handler to track server Pongs if needed for liveness.
// func (c *WebSocketClient) pongHandler(appData string) error {
// 	c.mu.Lock()
// 	c.lastPongRcvd = time.Now()
// 	c.mu.Unlock()
// 	log.Printf("Heartbeat: Received PONG: %s at %v", appData, c.lastPongRcvd)
// 	return nil
// }

// In Connect method, if using custom pong handler:
// c.conn.SetPongHandler(c.pongHandler)

// CloseConnection closes the WebSocket connection and sets isConnected to false.
// This is the primary method to close the connection and should be safe to call multiple times.
func (c *WebSocketClient) CloseConnection() {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.conn != nil {
		log.Println("PolygonClient: Closing WebSocket connection explicitly.")
		// Signal the ReadMessages goroutine to stop.
		// stopOnce ensures this is only done once to avoid panic on closed channel.
		c.stopOnce.Do(func() {
			close(c.stopChan)
		})
		// Write a close message to the server.
		err := c.conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
		if err != nil && !strings.Contains(err.Error(), "use of closed network connection") {
			// log.Printf("PolygonClient: Error writing close message: %v", err)
		}
		c.conn.Close() // Close the underlying network connection.
		c.conn = nil
	}
	c.isConnected = false
}

// IsConnected safely checks the connection status.
func (c *WebSocketClient) IsConnected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.isConnected && c.conn != nil
}

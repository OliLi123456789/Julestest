// webapp/frontend/src/services/websocketService.js
let socket = null;
let onOrderUpdateCallback = null;
let onPositionUpdateCallback = null;
// Add other callbacks for different message types as needed e.g. onAccountUpdateCallback
import { notificationService } from './notificationService'; // Import notificationService

const WEBSOCKET_RECONNECT_TIMEOUT = 5000; // 5 seconds
let currentApiToken = null; // Store the token for reconnect attempts

const connect = (apiToken) => {
    if (!apiToken) {
        console.error("WebSocketService: No API token provided for connection.");
        return;
    }
    currentApiToken = apiToken; // Store for potential reconnects

    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        console.log("WebSocketService: Already connected or connecting.");
        return;
    }

    // Adjust protocol and host/port as needed for your dev environment
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    // Assumes FastAPI backend is on same host/port for production.
    // For development, if frontend (e.g. :3000) and backend (e.g. :8000) are different,
    // explicitly set the backend host/port.
    let wsHost = window.location.host;
    if (process.env.NODE_ENV === 'development' && process.env.REACT_APP_WEBSOCKET_HOST) {
        // Example: REACT_APP_WEBSOCKET_HOST=localhost:8000 in .env file
        wsHost = process.env.REACT_APP_WEBSOCKET_HOST;
    } else if (process.env.NODE_ENV === 'development') {
        // Fallback for dev if specific host not set, assumes backend on 8000
        // This might need adjustment based on actual dev setup.
        // wsHost = `${window.location.hostname}:8000`;
        // For the current project structure, dev server proxies to :8000, so window.location.host should be fine.
    }

    const wsUrl = `${wsProtocol}//${wsHost}/ws/user?token=${apiToken}`;
    console.log(`WebSocketService: Connecting to ${wsUrl}`);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('WebSocketService: Connection established for user data.');
        notificationService.showSuccess("WebSocket connected to server.");
        // Optional: Send a ping or initial message if required by backend
        // sendPing();
    };

    socket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            console.log('WebSocketService: Message received:', message);
            if (message.type === 'ORDER_UPDATE' && onOrderUpdateCallback) {
                onOrderUpdateCallback(message.data);
            } else if (message.type === 'EXECUTION_REPORT' && onOrderUpdateCallback) {
                // Execution reports also update order status
                onOrderUpdateCallback(message.data);
            } else if (message.type === 'POSITION_UPDATE' && onPositionUpdateCallback) {
                onPositionUpdateCallback(message.data);
            } else if (message.type === 'PONG') {
                 console.log('WebSocketService: Pong received at', new Date(message.timestamp * 1000).toLocaleTimeString());
            }
            // Add more message type handlers here (e.g., account summary, P&L updates)
        } catch (error) {
            console.error('WebSocketService: Error processing message:', error, "Data:", event.data);
        }
    };

    socket.onerror = (error) => {
        console.error('WebSocketService: Error occurred:', error);
        notificationService.showError("WebSocket connection error. See console for details.");
        // UI error callback could be invoked here if needed
    };

    socket.onclose = (event) => {
        console.log(`WebSocketService: Connection closed. Code: ${event.code}, Reason: "${event.reason}"`);
        const wasConnected = socket !== null; // Check if socket was previously set (implies an attempt was made)
        socket = null;

        // Attempt to reconnect if not a normal closure (1000) and a token is available
        if (event.code !== 1000 && currentApiToken && wasConnected) {
            notificationService.showWarning(`WebSocket disconnected. Attempting to reconnect...`);
            console.log(`WebSocketService: Attempting to reconnect in ${WEBSOCKET_RECONNECT_TIMEOUT / 1000}s...`);
            setTimeout(() => connect(currentApiToken), WEBSOCKET_RECONNECT_TIMEOUT);
        } else if (event.code === 1000) {
            // notificationService.showInfo("WebSocket connection closed."); // Can be noisy
            console.log("WebSocketService: Connection closed normally.");
        } else if (!currentApiToken && wasConnected) {
            notificationService.showInfo("WebSocket disconnected (logged out).");
            console.log("WebSocketService: Not reconnecting, API token is null (likely logged out).");
        }
    };
};

const disconnect = () => {
    currentApiToken = null; // Clear token to prevent reconnect on explicit disconnect
    if (socket) {
        console.log("WebSocketService: Closing connection explicitly.");
        socket.close(1000, "User initiated disconnect"); // Normal closure code
    }
    // socket variable will be nulled out by onclose handler.
    // Clear callbacks
    onOrderUpdateCallback = null;
    onPositionUpdateCallback = null;
};

const setOnOrderUpdate = (callback) => { onOrderUpdateCallback = callback; };
const setOnPositionUpdate = (callback) => { onPositionUpdateCallback = callback; };

const sendPing = () => {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send("ping"); // Backend expects simple text "ping"
        console.log("WebSocketService: Ping sent.");
    } else {
        console.warn("WebSocketService: Cannot send ping, socket not open or not initialized.");
    }
};

// For future use: sending structured messages to backend via WebSocket
// const sendMessage = (messageObject) => {
//     if (socket && socket.readyState === WebSocket.OPEN) {
//         socket.send(JSON.stringify(messageObject));
//     } else {
//         console.warn("WebSocketService: Cannot send message, socket not open.");
//     }
// };

export const websocketService = { // Export as a named object
    connect,
    disconnect,
    setOnOrderUpdate,
    setOnPositionUpdate,
    sendPing,
    // sendMessage,
};

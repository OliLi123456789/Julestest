import React, { useState, useEffect } from 'react';
import './App.css'; // Default CRA CSS, can be modified or removed
import LoginForm from './components/LoginForm';
import ChartDisplay from './components/ChartDisplay';
import OrderEntryForm from './components/OrderEntryForm';
import OrdersView from './components/OrdersView';
import ChatWindow from './components/ChatWindow'; // Import ChatWindow
import { websocketService } from './services/websocketService';
import { notificationService } from './services/notificationService'; // Import notificationService

// TODO: This key should ideally come from a .env file or other configuration mechanism
const LLM_SERVICE_API_KEY_PLACEHOLDER = "dev_llm_service_key"; // Placeholder for LLM Service API Key

function App() {
  const [apiToken, setApiToken] = useState(localStorage.getItem('apiToken') || null);
  const [currentSymbol, setCurrentSymbol] = useState('AAPL'); // Default symbol

  // For now, lastSubmittedOrder is kept to show how OrdersView might have previously refreshed.
  // With WebSockets, this direct prop might become less important for triggering updates in OrdersView,
  // as updates will flow from WebSocket -> App.js state -> OrdersView props.
  const [lastSubmittedOrder, setLastSubmittedOrder] = useState(null);

  // Placeholder state for orders and positions that would be updated by WebSockets
  // In a real app, these would be properly managed (e.g., updating existing items, adding new ones)
  const [orders, setOrders] = useState([]);
  const [positions, setPositions] = useState([]);


  useEffect(() => {
    // Persist token to local storage
    if (apiToken) {
      localStorage.setItem('apiToken', apiToken);
      // Connect WebSocket when token is available
      websocketService.connect(apiToken);

      websocketService.setOnOrderUpdate((updatedOrderData) => {
          console.log("App.js: WebSocket received ORDER_UPDATE:", updatedOrderData);
          setOrders(prevOrders => {
              const index = prevOrders.findIndex(o => o.order_id === updatedOrderData.order_id);
              if (index !== -1) {
                  const newOrders = [...prevOrders];
                  newOrders[index] = updatedOrderData;
                  return newOrders;
              } else {
                  return [...prevOrders, updatedOrderData];
              }
          });
          // Notify based on status
          if (updatedOrderData.status === 'FILLED' || updatedOrderData.status === 'PARTIALLY_FILLED') {
            notificationService.showSuccess(`Order ${updatedOrderData.symbol} ${updatedOrderData.status}! Qty: ${updatedOrderData.filled_quantity || updatedOrderData.quantity}`);
          } else if (updatedOrderData.status === 'REJECTED' || updatedOrderData.status === 'CANCELLED' || updatedOrderData.status === 'EXPIRED') {
            notificationService.showError(`Order ${updatedOrderData.symbol} ${updatedOrderData.status}. Reason: ${updatedOrderData.reason || 'N/A'}`);
          } else {
            notificationService.showInfo(`Order ${updatedOrderData.symbol} status: ${updatedOrderData.status}`);
          }
      });

      websocketService.setOnPositionUpdate((updatedPositionData) => {
          console.log("App.js: WebSocket received POSITION_UPDATE:", updatedPositionData);
          setPositions(prevPositions => {
              const index = prevPositions.findIndex(p => p.symbol === updatedPositionData.symbol && p.user_id === updatedPositionData.user_id);
              if (index !== -1) {
                  const newPositions = [...prevPositions];
                  newPositions[index] = updatedPositionData;
                  return newPositions;
              } else {
                  return [...prevPositions, updatedPositionData];
              }
          });
          notificationService.showInfo(`Position update for ${updatedPositionData.symbol}: Qty ${updatedPositionData.quantity}`);
      });

      // Setup a ping interval to keep connection alive or check status
      const pingIntervalId = setInterval(() => websocketService.sendPing(), 30000); // Ping every 30s

      return () => { // Cleanup function when apiToken changes or component unmounts
          console.log("App.js: Cleaning up WebSocket connection and ping interval.");
          clearInterval(pingIntervalId);
          websocketService.disconnect();
          // Clear listeners
          websocketService.setOnOrderUpdate(null);
          websocketService.setOnPositionUpdate(null);
      };

    } else {
      localStorage.removeItem('apiToken');
      websocketService.disconnect(); // Ensure disconnection if token is removed (logout)
    }
  }, [apiToken]); // This effect runs when apiToken changes

  const handleLogin = (token) => {
    setApiToken(token);
  };

  const handleLogout = () => {
    setApiToken(null); // This will trigger the useEffect cleanup
  };

  const handleOrderSubmitted = (order) => {
    console.log("New order submitted in App.js:", order);
    setLastSubmittedOrder(order); // Update state to trigger refresh in OrdersView
    // Potentially update currentSymbol or other app state based on the order
    if(order.symbol) {
      setCurrentSymbol(order.symbol);
    }
  };

  // Basic styling for layout (can be moved to App.css)
  const appStyle = {
    fontFamily: 'Arial, sans-serif',
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '20px',
  };

  const headerStyle = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottom: '2px solid #eee',
    paddingBottom: '10px',
    marginBottom: '20px',
  };

  const tradingSectionStyle = {
    display: 'flex',
    gap: '20px',
  };

  const mainPanelStyle = {
    flex: 3, // Takes 3/4 of the space
  };

  const sidePanelStyle = {
    flex: 1, // Takes 1/4 of the space
  };


  if (!apiToken) {
    return (
      <div style={appStyle}>
        <LoginForm onLogin={handleLogin} />
      </div>
    );
  }

  return (
    <div style={appStyle}>
      <div style={headerStyle}>
        <h1>Trading Platform</h1>
        <div>
          <span>Logged in as: (testuser) </span> {/* Placeholder user display */}
          <button onClick={handleLogout}>Logout</button>
        </div>
      </div>

      <p>Selected Symbol for Chart:
        <input
          type="text"
          value={currentSymbol}
          onChange={(e) => setCurrentSymbol(e.target.value.toUpperCase())}
          placeholder="Enter Symbol (e.g. GOOG)"
        />
      </p>

      <div style={tradingSectionStyle}>
        <div style={mainPanelStyle}>
          <ChartDisplay symbol={currentSymbol} />
          <OrderEntryForm apiToken={apiToken} onOrderSubmit={handleOrderSubmitted} />
        </div>
        <div style={sidePanelStyle}>
          {/* Pass the 'orders' state (updated by WebSockets) to OrdersView */}
          {/* Remove newSubmittedOrder prop if it's no longer the primary trigger for OrdersView updates */}
          <OrdersView apiToken={apiToken} orders={orders} />
          {/* Placeholder for PositionsView, which would consume the 'positions' state */}
          {/* <PositionsView apiToken={apiToken} positions={positions} /> */}
        </div>
      </div>

      {/* LLM Chat Section */}
      <div className="llm-chat-section" style={{ marginTop: '30px', borderTop: '2px solid #eee', paddingTop: '20px'}}>
        <h2>AI Chat Assistant</h2>
        <ChatWindow
          apiToken={LLM_SERVICE_API_KEY_PLACEHOLDER} // This is the API key FOR THE LLM SERVICE
          initialSessionId={`user_testuser_chat_${Date.now()}`} // Example session ID
          currentUsername={"testuser_chat"} // Placeholder username
        />
      </div>
    </div>
  );
}

export default App;

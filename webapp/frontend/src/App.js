import React, { useState, useEffect } from 'react';
import './App.css'; // Default CRA CSS, can be modified or removed
import LoginForm from './components/LoginForm';
import ChartDisplay from './components/ChartDisplay';
import OrderEntryForm from './components/OrderEntryForm';
import OrdersView from './components/OrdersView';
import ChatPage from './components/ChatPage'; // Import ChatPage

function App() {
  const [apiToken, setApiToken] = useState(localStorage.getItem('apiToken') || null);
  const [currentSymbol, setCurrentSymbol] = useState('AAPL'); // Default symbol
  const [lastSubmittedOrder, setLastSubmittedOrder] = useState(null); // To trigger OrdersView refresh
  const [showChatView, setShowChatView] = useState(false); // State for toggling view

  useEffect(() => {
    // Persist token to local storage
    if (apiToken) {
      localStorage.setItem('apiToken', apiToken);
    } else {
      localStorage.removeItem('apiToken');
    }
  }, [apiToken]);

  const handleLogin = (token) => {
    setApiToken(token);
  };

  const handleLogout = () => {
    setApiToken(null);
    // Optionally, could also call a backend /auth/logout endpoint if it existed
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
          <button onClick={() => setShowChatView(!showChatView)} style={{ marginRight: '10px', padding: '8px 12px', cursor: 'pointer' }}>
            {showChatView ? 'Trading View' : 'AI Chat View'}
          </button>
          <span>Logged in as: (testuser) </span> {/* Placeholder user display */}
          <button onClick={handleLogout} style={{ padding: '8px 12px', cursor: 'pointer' }}>Logout</button>
        </div>
      </div>

      {showChatView ? (
        <ChatPage />
      ) : (
        <>
          {/* Existing Trading Platform UI */}
          <p>Selected Symbol for Chart:
            <input
              type="text"
              value={currentSymbol}
              onChange={(e) => setCurrentSymbol(e.target.value.toUpperCase())}
              placeholder="Enter Symbol (e.g. GOOG)"
              style={{ marginLeft: '10px', padding: '5px' }}
            />
          </p>
          <div style={tradingSectionStyle}>
            <div style={mainPanelStyle}>
              <ChartDisplay symbol={currentSymbol} />
              <OrderEntryForm apiToken={apiToken} onOrderSubmit={handleOrderSubmitted} />
            </div>
            <div style={sidePanelStyle}>
              <OrdersView apiToken={apiToken} newSubmittedOrder={lastSubmittedOrder} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default App;

import React, { useState, useEffect, useCallback } from 'react';

// Receives 'orders' prop from App.js, which is updated by WebSockets.
function OrdersView({ apiToken, orders }) { // Renamed ordersFromProps to orders for clarity
  const [error, setError] = useState(''); // For errors related to single order status fetch or manual refresh
  const [isLoadingManualRefresh, setIsLoadingManualRefresh] = useState(false);

  const [selectedOrderId, setSelectedOrderId] = useState(null);
  const [selectedOrderStatus, setSelectedOrderStatus] = useState(null);

  // Manual refresh capability (optional)
  const handleManualRefresh = useCallback(async () => {
    if (!apiToken) {
      setError('Login required to refresh orders.');
      return;
    }
    setIsLoadingManualRefresh(true);
    setError('');
    try {
      const response = await fetch('/orders', { // Fetches all orders
        headers: { 'Authorization': `Bearer ${apiToken}` },
      });
      if (response.ok) {
        const data = await response.json();
        console.log("OrdersView: Manual refresh fetched data:", data);
        alert(`Manual refresh fetched ${data.length} orders. This component primarily updates via WebSockets. Check console for fetched data. App's main order list is not updated by this button.`);
        // NOTE: This manual refresh does NOT update the 'orders' prop displayed by this component,
        // as that comes from App.js. This is for debug/manual-check purposes only.
        // To update the main list, App.js would need to expose a refresh function.
      } else {
        const errData = await response.json();
        setError(`Manual refresh failed: ${errData.detail || response.statusText}`);
      }
    } catch (err) {
      setError(`Manual refresh network error: ${err.message}`);
      console.error("Manual refresh fetch orders error:", err);
    } finally {
      setIsLoadingManualRefresh(false);
    }
  }, [apiToken]);

  useEffect(() => {
    // This effect can be used to observe changes to the orders prop if needed for debugging
    // console.log("OrdersView: 'orders' prop updated, count:", orders ? orders.length : 0);
  }, [orders]);

  const handleViewOrderStatus = async (orderId) => {
    setSelectedOrderId(orderId);
    setSelectedOrderStatus('Loading...');
    if (!apiToken) {
        setSelectedOrderStatus('Error: Not logged in.');
        return;
    }
    try {
        const response = await fetch(`/orders/${orderId}`, {
            headers: { 'Authorization': `Bearer ${apiToken}` },
        });
        if (response.ok) {
            const data = await response.json();
            // Display more comprehensive status details
            let statusString = `Status: ${data.status}`;
            if (data.filled_quantity) statusString += `, Filled: ${data.filled_quantity}/${data.quantity}`;
            if (data.average_fill_price) statusString += ` @ ${data.average_fill_price}`;
            if (data.broker_order_id) statusString += ` (BrokerID: ${data.broker_order_id})`;
            if (data.reason) statusString += ` Reason: ${data.reason}`;
            statusString += `, Updated: ${new Date().toLocaleTimeString()}`;
            setSelectedOrderStatus(statusString);
        } else {
            const errData = await response.json();
            setSelectedOrderStatus(`Error: ${errData.detail || response.statusText}`);
        }
    } catch (err) {
        setSelectedOrderStatus(`Network error: ${err.message}`);
        console.error("Fetch single order status error:", err);
    }
  };

  return (
    <div style={{ border: '1px solid #ccc', padding: '20px', margin: '10px 0' }}>
      <h3>My Orders</h3>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      <button onClick={handleManualRefresh} disabled={isLoadingManualRefresh}>
        {isLoadingManualRefresh ? 'Refreshing...' : 'Manual Full Refresh (Logs to Console)'}
      </button>

      {/* Displaying orders from props */}
      {!orders || orders.length === 0 ? (
        <p>No orders found. Waiting for updates via WebSocket or manual refresh...</p>
      ) : (
        <ul style={{ listStyleType: 'none', padding: 0 }}>
          {orders.map(order => (
            <li key={order.order_id} style={{ borderBottom: '1px solid #eee', padding: '10px 0' }}>
              <strong>ID:</strong> {order.order_id} (User: {order.user_id}) <br />
              <strong>Symbol:</strong> {order.symbol} <br />
              <strong>Type:</strong> {order.order_type} {order.price ? `@ ${order.price}` : (order.limit_price ? `@ ${order.limit_price}` : '')}<br />
              <strong>Qty:</strong> {order.quantity} (Filled: {order.filled_quantity || 0}, Rem: {order.remaining_quantity !== undefined ? order.remaining_quantity : order.quantity - (order.filled_quantity || 0) }) <br />
              <strong>Status:</strong> {order.status} <br />
              {order.average_fill_price && parseFloat(order.average_fill_price) > 0 && <><strong>Avg Fill Price:</strong> {order.average_fill_price}<br /></>}
              {order.commission && <><strong>Commission:</strong> {order.commission}<br /></>}
              {order.broker_order_id && <><strong>Broker ID:</strong> {order.broker_order_id}<br /></>}
              {order.reason && <><strong>Reason:</strong> {order.reason}<br /></>}
              {order.timestamp_utc && <><strong>Last Update:</strong> {new Date(order.timestamp_utc).toLocaleString()}<br /></>}
              <button onClick={() => handleViewOrderStatus(order.order_id)}>Check Detail Status</button>
              {selectedOrderId === order.order_id && selectedOrderStatus && (
                <p style={{fontSize: '0.9em', color: 'blue', marginTop: '5px'}}>{selectedOrderStatus}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      <p><em>(This view updates live from WebSocket data managed by App.js. Positions view is separate.)</em></p>
    </div>
  );
}

export default OrdersView;

import React, { useState, useEffect, useCallback } from 'react';

function OrdersView({ apiToken, newSubmittedOrder }) {
  const [orders, setOrders] = useState([]);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState(null);
  const [selectedOrderStatus, setSelectedOrderStatus] = useState(null);

  const fetchOrders = useCallback(async () => {
    if (!apiToken) {
      setError('Not logged in or API token not available.');
      setOrders([]);
      return;
    }
    setIsLoading(true);
    setError('');
    try {
      const response = await fetch('/orders', {
        headers: { 'x-token': apiToken },
      });
      if (response.ok) {
        const data = await response.json();
        setOrders(data);
      } else {
        const errData = await response.json();
        setError(`Failed to fetch orders: ${errData.detail || response.statusText}`);
        setOrders([]);
      }
    } catch (err) {
      setError(`Network error: ${err.message}`);
      setOrders([]);
      console.error("Fetch orders error:", err);
    } finally {
      setIsLoading(false);
    }
  }, [apiToken]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders, newSubmittedOrder]); // Re-fetch if a new order is submitted via props

  const handleViewOrderStatus = async (orderId) => {
    setSelectedOrderId(orderId);
    setSelectedOrderStatus('Loading...');
    if (!apiToken) {
        setSelectedOrderStatus('Error: Not logged in.');
        return;
    }
    try {
        const response = await fetch(`/orders/${orderId}`, {
            headers: { 'x-token': apiToken },
        });
        if (response.ok) {
            const data = await response.json();
            setSelectedOrderStatus(`Status: ${data.status}, Symbol: ${data.symbol}, Qty: ${data.quantity}, Price: ${data.price || 'N/A'}, Updated: ${new Date().toLocaleTimeString()}`);
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
      <h3>My Orders / Positions</h3>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <button onClick={fetchOrders} disabled={isLoading}>
        {isLoading ? 'Loading...' : 'Refresh Orders'}
      </button>
      {isLoading && <p>Loading orders...</p>}
      {!isLoading && orders.length === 0 && !error && <p>No orders found.</p>}
      {orders.length > 0 && (
        <ul style={{ listStyleType: 'none', padding: 0 }}>
          {orders.map(order => (
            <li key={order.order_id} style={{ borderBottom: '1px solid #eee', padding: '10px 0' }}>
              <strong>ID:</strong> {order.order_id} <br />
              <strong>Symbol:</strong> {order.symbol} <br />
              <strong>Type:</strong> {order.order_type} <br />
              <strong>Qty:</strong> {order.quantity} <br />
              <strong>Price:</strong> {order.price || 'Market'} <br />
              <strong>Status:</strong> {order.status} <br />
              <button onClick={() => handleViewOrderStatus(order.order_id)}>Check Status</button>
              {selectedOrderId === order.order_id && selectedOrderStatus && (
                <p style={{fontSize: '0.9em', color: 'blue', marginTop: '5px'}}>{selectedOrderStatus}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      <p><em>(Positions view is not implemented yet - this only shows orders)</em></p>
    </div>
  );
}

export default OrdersView;

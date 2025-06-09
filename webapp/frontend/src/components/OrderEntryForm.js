import React, { useState } from 'react';

function OrderEntryForm({ apiToken, onOrderSubmit }) {
  const [symbol, setSymbol] = useState('AAPL'); // Default symbol
  const [quantity, setQuantity] = useState('');
  const [orderType, setOrderType] = useState('MARKET'); // 'MARKET' or 'LIMIT'
  const [price, setPrice] = useState(''); // Only for LIMIT orders
  const [message, setMessage] = useState(''); // For success/error messages

  const handleSubmit = async (event) => {
    event.preventDefault();
    setMessage('');

    if (!apiToken) {
        setMessage('Error: You are not logged in.');
        return;
    }

    if (!symbol || !quantity) {
        setMessage('Symbol and Quantity are required.');
        return;
    }
    if (orderType === 'LIMIT' && !price) {
        setMessage('Price is required for LIMIT orders.');
        return;
    }
    const qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty <= 0) {
        setMessage('Quantity must be a positive number.');
        return;
    }
    const prc = orderType === 'LIMIT' ? parseFloat(price) : null;
    if (orderType === 'LIMIT' && (isNaN(prc) || prc <= 0)) {
        setMessage('Price must be a positive number for LIMIT orders.');
        return;
    }

    const orderData = {
      symbol,
      quantity: qty,
      order_type: orderType,
      price: prc,
    };

    try {
      const response = await fetch('/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-token': apiToken, // Send the mock token in the header
        },
        body: JSON.stringify(orderData),
      });

      const responseData = await response.json();
      if (response.ok) {
        setMessage(`Order submitted successfully! Order ID: ${responseData.order_id}, Status: ${responseData.status}`);
        if(onOrderSubmit) onOrderSubmit(responseData); // Callback for parent component
        // Clear form
        // setSymbol(''); // Or keep symbol for next order
        setQuantity('');
        setPrice('');
      } else {
        setMessage(`Error: ${responseData.detail || 'Failed to submit order'}`);
      }
    } catch (err) {
      setMessage(`Network error: ${err.message}`);
      console.error("Order submission error:", err);
    }
  };

  return (
    <div style={{ border: '1px solid #ccc', padding: '20px', margin: '10px 0' }}>
      <h3>Order Entry</h3>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="symbol">Symbol:</label>
          <input
            type="text"
            id="symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            required
          />
        </div>
        <div>
          <label htmlFor="quantity">Quantity:</label>
          <input
            type="number"
            id="quantity"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="orderType">Order Type:</label>
          <select id="orderType" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <option value="MARKET">Market</option>
            <option value="LIMIT">Limit</option>
          </select>
        </div>
        {orderType === 'LIMIT' && (
          <div>
            <label htmlFor="price">Price:</label>
            <input
              type="number"
              id="price"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              step="0.01"
              required
            />
          </div>
        )}
        {message && <p>{message}</p>}
        <button type="submit">Submit Order</button>
      </form>
    </div>
  );
}

export default OrderEntryForm;

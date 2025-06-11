import React, { useState } from 'react';
import { notificationService } from '../services/notificationService'; // Import notificationService

function OrderEntryForm({ apiToken, onOrderSubmit }) {
  const [symbol, setSymbol] = useState('AAPL'); // Default symbol
  const [quantity, setQuantity] = useState('');
  const [orderType, setOrderType] = useState('MARKET'); // 'MARKET' or 'LIMIT'
  const [price, setPrice] = useState(''); // Only for LIMIT orders
  const [message, setMessage] = useState(''); // For local success/error messages in form

  const handleSubmit = async (event) => {
    event.preventDefault();
    setMessage(''); // Clear previous local messages

    if (!apiToken) {
        const errMsg = 'You must be logged in to submit an order.';
        setMessage(errMsg);
        notificationService.showError(errMsg);
        return;
    }

    if (!symbol.trim() || !quantity.trim()) {
        const errMsg = 'Symbol and Quantity are required.';
        setMessage(errMsg);
        notificationService.showWarning(errMsg);
        return;
    }
    if (orderType === 'LIMIT' && !price.trim()) {
        const errMsg = 'Price is required for LIMIT orders.';
        setMessage(errMsg);
        notificationService.showWarning(errMsg);
        return;
    }

    const qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty <= 0) {
        const errMsg = 'Quantity must be a positive number.';
        setMessage(errMsg);
        notificationService.showWarning(errMsg);
        return;
    }

    let prc = null;
    if (orderType === 'LIMIT') {
        prc = parseFloat(price);
        if (isNaN(prc) || prc <= 0) {
            const errMsg = 'Price must be a positive number for LIMIT orders.';
            setMessage(errMsg);
            notificationService.showWarning(errMsg);
            return;
        }
    }

    const orderData = {
      symbol: symbol.trim().toUpperCase(),
      quantity: qty,
      order_type: orderType,
      price: prc, // Will be null for MARKET orders
    };

    try {
      const response = await fetch('/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiToken}`,
        },
        body: JSON.stringify(orderData),
      });

      // Try to parse JSON regardless of response.ok, as FastAPI often sends JSON error details
      let responseData;
      try {
          responseData = await response.json();
      } catch (jsonError) {
          // If JSON parsing fails, use text content if available, or status text
          const responseText = await response.text().catch(() => response.statusText);
          responseData = { detail: responseText || response.statusText };
          console.error("Order submission: Non-JSON response or JSON parse error", responseData.detail);
      }

      if (response.ok) {
        const successMsg = `Order ${responseData.order_id || orderData.symbol} submitted (${responseData.status || 'processing'}).`;
        setMessage(successMsg); // Local message
        notificationService.showSuccess(`Order for ${orderData.symbol} submitted. ID: ${responseData.order_id}`);

        if(onOrderSubmit) onOrderSubmit(responseData);

        // Clear form fields for next order
        setQuantity('');
        setPrice('');
        // Optionally keep symbol: setSymbol('AAPL'); or clear: setSymbol('');
      } else {
        // Use detail from JSON response if available, otherwise default message
        const errorDetail = responseData.detail?.message || responseData.detail || 'Failed to submit order. Please try again.';
        setMessage(`Error: ${errorDetail}`); // Local message
        notificationService.showError(`Order Error: ${errorDetail}`);
      }
    } catch (err) {
      // Network error or other issues
      const networkErrorMsg = `Order submission failed: ${err.message || "Network error"}`;
      setMessage(networkErrorMsg); // Local message
      notificationService.showError(networkErrorMsg);
      console.error("Order submission error (catch block):", err);
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
            onChange={(e) => setSymbol(e.target.value)} // Uppercasing moved to submit
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
          <select id="orderType" value={orderType} onChange={(e) => { setOrderType(e.target.value); if (e.target.value === 'MARKET') setPrice(''); }}>
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
              required={orderType === 'LIMIT'} // Required only if orderType is LIMIT
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

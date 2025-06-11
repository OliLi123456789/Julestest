// webapp/frontend/src/components/MessageInput.js
import React, { useState } from 'react';

const MessageInput = ({ onSendMessage, isLoading }) => {
  const [inputValue, setInputValue] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim() && !isLoading) {
      onSendMessage(inputValue.trim());
      setInputValue('');
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', padding: '10px', borderTop: '1px solid #eee' }}>
      <input
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        style={{ flexGrow: 1, padding: '10px', borderRadius: '20px', border: '1px solid #ccc', marginRight: '10px' }}
        placeholder="Type your message..."
        disabled={isLoading}
      />
      <button type="submit" style={{
        padding: '10px 20px',
        borderRadius: '20px',
        border: 'none',
        backgroundColor: isLoading ? '#ccc' : '#007bff',
        color: 'white',
        cursor: isLoading ? 'not-allowed' : 'pointer'
      }} disabled={isLoading}>
        {isLoading ? 'Sending...' : 'Send'}
      </button>
    </form>
  );
};

export default MessageInput;

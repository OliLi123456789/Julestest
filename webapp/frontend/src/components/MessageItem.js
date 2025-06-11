// webapp/frontend/src/components/MessageItem.js
import React from 'react';

const MessageItem = ({ message }) => {
  const isUser = message.sender === 'user';

  const messageStyle = {
    display: 'flex',
    justifyContent: isUser ? 'flex-end' : 'flex-start',
    margin: '10px 0',
  };

  const bubbleStyle = {
    padding: '10px 15px',
    borderRadius: '20px',
    backgroundColor: isUser ? '#007bff' : '#e9ecef',
    color: isUser ? 'white' : 'black',
    maxWidth: '70%',
    wordWrap: 'break-word',
  };

  return (
    <div style={messageStyle}>
      <div style={bubbleStyle}>
        {message.text}
      </div>
    </div>
  );
};

export default MessageItem;

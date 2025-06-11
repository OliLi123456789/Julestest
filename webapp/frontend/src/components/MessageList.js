// webapp/frontend/src/components/MessageList.js
import React, { useEffect, useRef } from 'react';
// Import MessageItem once created
import MessageItem from './MessageItem';

const MessageList = ({ messages, isLoading }) => {
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages, isLoading]);

  return (
    <div style={{ flexGrow: 1, overflowY: 'auto', padding: '10px' }}>
      {messages.map(msg => (
        <MessageItem key={msg.id} message={msg} />
      ))}
      {isLoading && (
        <div style={{ fontStyle: 'italic', textAlign: 'center', padding: '10px', color: '#777' }}>
          Assistant is typing...
        </div>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
};

export default MessageList;

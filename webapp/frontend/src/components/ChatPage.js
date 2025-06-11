// webapp/frontend/src/components/ChatPage.js
import React, { useState, useEffect } from 'react';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import { sendMessageToBot } from '../services/chatService'; // Import the service

const ChatPage = () => {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState('');

  useEffect(() => {
    const newSessionId = Date.now().toString(36) + Math.random().toString(36).substring(2);
    setSessionId(newSessionId);
    setMessages([
      { id: `bot-initial-${newSessionId}`, text: 'Welcome to the AI Assistant! How can I help you today?', sender: 'bot' }
    ]);
  }, []);

  const handleSendMessage = async (inputText) => {
    setError(null);
    const newUserMessageId = `user-${Date.now().toString(36)}-${Math.random().toString(36).substring(2)}`;
    const newUserMessage = {
      id: newUserMessageId,
      text: inputText,
      sender: 'user',
    };
    setMessages(prevMessages => [...prevMessages, newUserMessage]);
    setIsLoading(true);

    try {
      // Call the API service
      // userId can be a hardcoded string for now, e.g., "frontend_user_123"
      const backendResponse = await sendMessageToBot(inputText, sessionId, 'frontend_user_123');

      // Extract response text, and potentially other fields if needed later
      const botResponseText = backendResponse.response_text || "Sorry, I didn't get a proper response.";
      const generatedCode = backendResponse.generated_code; // Get the generated code

      const newBotMessageId = `bot-${Date.now().toString(36)}-${Math.random().toString(36).substring(2)}`;
      const newBotMessage = {
        id: newBotMessageId,
        text: botResponseText,
        sender: 'bot',
        // toolUsed: backendResponse.tool_used, // Example if you want to store these
        // toolResponse: backendResponse.tool_response,
      };

      if (generatedCode) {
        newBotMessage.code = generatedCode; // Add the 'code' property if it exists
      }

      setMessages(prevMessages => [...prevMessages, newBotMessage]);

    } catch (apiError) {
      console.error("handleSendMessage error:", apiError); // Log the full error
      setError(apiError.message || 'Failed to connect to the bot. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      // Adjusted height assuming some global margin/padding, e.g. 20px top/bottom from App.js style.
      // If App.js has padding 20px, and this has margin 20px, total vertical space used is 40px top, 40px bottom.
      // Let's assume header in App.js is ~60px. Total ~140px.
      height: 'calc(100vh - 140px)',
      border: '1px solid #ccc',
      margin: '20px auto', // Centering with auto margins
      borderRadius: '8px',
      fontFamily: 'Arial, sans-serif', // Moved from outer div for self-containment
      maxWidth: '800px', // Constrain chat window width
      boxSizing: 'border-box' // Ensure padding/border don't expand total width/height
    }}>
      <h2 style={{
        textAlign: 'center',
        padding: '15px 0', // Slightly more padding
        borderBottom: '1px solid #eee',
        margin: 0,
        fontSize: '1.5em', // Larger font size
        color: '#333' // Darker color for header
       }}>
        AI Assistant (Session: {sessionId ? sessionId.substring(0, 8) : '...'})
      </h2>
      <MessageList messages={messages} isLoading={isLoading} />
      {error && <p style={{ color: 'red', textAlign: 'center', padding: '5px', margin: '5px 0', borderTop: '1px solid #eee', borderBottom: '1px solid #eee', backgroundColor: '#ffe0e0' }}>Error: {error}</p>}
      <MessageInput onSendMessage={handleSendMessage} isLoading={isLoading} />
    </div>
  );
};

export default ChatPage;

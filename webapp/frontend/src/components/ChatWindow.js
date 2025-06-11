// webapp/frontend/src/components/ChatWindow.js
import React, { useState, useEffect, useRef } from 'react';
import notificationService from '../services/notificationService'; // Assuming this exists
import NewsDisplay from './tool_displays/NewsDisplay';
import EarningsDisplay from './tool_displays/EarningsDisplay';

// Basic styling (can be moved to a CSS file)
const chatWindowStyle = { border: '1px solid #ccc', padding: '10px', height: '500px', display: 'flex', flexDirection: 'column', marginTop: '20px' };
const messagesAreaStyle = { flexGrow: 1, overflowY: 'auto', marginBottom: '10px', borderBottom: '1px solid #eee', paddingRight: '10px' };
const messageStyle = (isUser) => ({
    textAlign: isUser ? 'right' : 'left',
    margin: '5px',
    padding: '8px 12px',
    borderRadius: '10px',
    backgroundColor: isUser ? '#dcf8c6' : (type === 'error' ? '#ffebee' : '#f1f0f0'), // Light red for error
    color: type === 'error' ? '#c62828' : 'inherit', // Darker red text for error
    maxWidth: '70%',
    alignSelf: isUser ? 'flex-end' : 'flex-start',
    wordWrap: 'break-word',
    whiteSpace: 'pre-wrap', // To respect newlines in text
});
const inputAreaStyle = { display: 'flex', marginTop: 'auto' };
const inputStyle = { flexGrow: 1, marginRight: '10px', padding: '8px' };
const buttonStyle = { padding: '8px 15px' };
const codeBlockStyle = {
    backgroundColor: '#2d2d2d',
    color: '#f8f8f2',
    padding: '10px',
    borderRadius: '5px',
    overflowX: 'auto',
    whiteSpace: 'pre', // Keep pre formatting for code
    fontFamily: 'monospace'
};


function ChatWindow({ apiToken, initialSessionId, currentUsername }) { // Pass apiToken, initialSessionId, and currentUsername
    const [messages, setMessages] = useState([]); // { id, text, sender: 'user' | 'bot', type: 'text' | 'tool_response' | 'code', tool_data: {} }
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [currentSessionId, setCurrentSessionId] = useState(initialSessionId || `sess_${Date.now()}`);
    const [feedbackSent, setFeedbackSent] = useState({}); // { [messageId]: 'up' | 'down' }

    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(scrollToBottom, [messages]);

    // Effect to set initial message or update session ID if initialSessionId prop changes
    useEffect(() => {
        setCurrentSessionId(initialSessionId || `sess_${Date.now()}`);
        // Optionally, add a welcome message from the bot when session initializes
        // setMessages([{ id: 'welcome', text: 'Hello! How can I help you today?', sender: 'bot', type: 'text'}]);
    }, [initialSessionId]);


    const handleSendMessage = async (e) => {
        if (e) e.preventDefault();
        if (!input.trim()) return;

        const userMessageText = input;
        const userMessage = { id: `user_${Date.now()}`, text: userMessageText, sender: 'user', type: 'text' };
        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        try {
            const requestBody = {
                user_id: currentUsername || "chat_ui_user_anonymous",
                message: userMessageText,
                session_id: currentSessionId
            };

            console.log("Sending to /api/v1/chat:", JSON.stringify(requestBody, null, 2));
            console.log("Using X-API-Key:", apiToken ? apiToken.substring(0, 10) + "..." : "Not provided");


            const response = await fetch(`/api/v1/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': apiToken,
                },
                body: JSON.stringify(requestBody)
            });

            const data = await response.json();
            setIsLoading(false);

            if (!response.ok) { // HTTP error (e.g., 500, 401, 403)
                const errorDetail = data.detail || data.error_message || data.error?.message || `Chat API request failed with status ${response.status}`;
                notificationService.showError(`Chat Error: ${errorDetail}`);
                setMessages(prev => [...prev, {id: `bot_http_err_${Date.now()}`, text: `Error: ${errorDetail}`, sender: 'bot', type: 'error', raw_response: data}]);
                return;
            }

            // Check for error message within a successful (e.g., 200 OK) response from LLM service
            if (data.error_message) {
                notificationService.showError(`Chatbot Error: ${data.error_message}`);
                setMessages(prev => [...prev, {
                    id: `bot_llm_err_${Date.now()}`,
                    text: `Sorry, I encountered an issue: ${data.error_message}`,
                    sender: 'bot',
                    type: 'error',
                    raw_response: data
                }]);
                return; // Stop further processing for this message
            }

            if (data.session_id && data.session_id !== currentSessionId) {
                setCurrentSessionId(data.session_id);
            }

            let botResponseText = data.response_text; // This is the summary or main text from LLM
            let botMessageType = 'text'; // Default type

            // The `data` object is the full LLMResponse from the backend.
            // It includes: response_text, generated_code, tool_used, tool_response (summary),
            // structured_tool_data, tool_data_type.

            if (data.generated_code) {
                botMessageType = 'code';
                // botResponseText remains data.response_text (e.g., "Here's the code...")
                // The actual code is in data.generated_code, handled by renderMessageContent
            } else if (data.tool_used) {
                // If a tool was used, data.tool_response is the summary text.
                // data.response_text might be the same, or an LLM's further processing of it.
                // For now, we assume data.response_text is the primary text to display.
                botMessageType = data.tool_data_type || 'tool_response'; // Use specific type if available
            }

            if (data.rag_context_used && !data.generated_code) {
                 // Prepend RAG notice to the main response text if not code gen
                 // botResponseText is already data.response_text from LLM
                 if (!botResponseText.toLowerCase().startsWith("[using knowledge base]")) { // Avoid double-prepending
                    botResponseText = "[Using Knowledge Base]\n" + botResponseText;
                 }
            }

            const botMessage = {
                id: `bot_${Date.now()}`,
                text: botResponseText, // This is the primary textual response for the message bubble
                sender: 'bot',
                type: botMessageType, // 'code', 'news_articles', 'earnings_reports', or 'text'/'tool_response'
                raw_response: data // Store the full LLMResponse from backend
            };
            setMessages(prev => [...prev, botMessage]);

        } catch (error) {
            setIsLoading(false);
            notificationService.showError(`Failed to send message: ${error.message}`);
            setMessages(prev => [...prev, {id: `catch_err_${Date.now()}`, text: `Error: ${error.message}`, sender: 'bot', type: 'error'}]);
        }
    };

    const handleClearChat = async () => {
        if (!currentSessionId) {
            notificationService.showWarning("No active chat session to clear.");
            return;
        }
        const confirmClear = window.confirm("Are you sure you want to clear the current chat history? This action cannot be undone.");
        if (!confirmClear) {
            return;
        }

        setIsLoading(true); // Indicate activity
        try {
            // console.log(`Attempting to clear session: /api/v1/chat/sessions/${currentSessionId}/clear with key ${apiToken ? apiToken.substring(0,5) : 'N/A'}`);
            const response = await fetch(`/api/v1/chat/sessions/${currentSessionId}/clear`, {
                method: 'POST',
                headers: {
                    'X-API-Key': apiToken, // Service API Key
                }
            });

            if (response.status === 204) { // Successfully cleared
                setMessages([]); // Clear local message display
                notificationService.showSuccess("Chat history cleared.");
                // Optional: Generate a new session ID to truly start fresh.
                // For now, keeps the same session_id, which is now empty on server.
                // setCurrentSessionId(`sess_${Date.now()}`);
                // console.log("Chat history cleared. Kept session ID or use above to start new.");
            } else {
                const errorText = await response.text(); // Get raw text for better debugging
                const errorData = JSON.parse(errorText || "{}"); // Try to parse, default to empty obj
                notificationService.showError(`Failed to clear chat: ${errorData.detail || response.statusText || errorText}`);
                console.error("Failed to clear chat session on backend:", response.status, errorData || errorText);
            }
        } catch (error) {
            notificationService.showError(`Error clearing chat: ${error.message}`);
            console.error("Network or other error clearing chat session:", error);
        } finally {
            setIsLoading(false);
        }
    };

    // renderMessageContent is removed, logic moved into the map function directly for clarity here.

    const handleFeedback = async (messageId, botMessageText, userQuery, rating) => {
        if (feedbackSent[messageId]) {
            notificationService.showInfo("Feedback already submitted for this message.");
            return;
        }

        // Using console.log for frontend logging in this component
        console.log(`Sending feedback: msgId=${messageId}, rating=${rating}, query='${userQuery}'`);
        try {
            const response = await fetch(`/api/v1/chat/feedback`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': apiToken,
                },
                body: JSON.stringify({
                    session_id: currentSessionId,
                    message_id: String(messageId),
                    user_id: currentUsername || "chat_ui_user_anonymous",
                    rating: rating,
                    comment: null,
                    bot_message_text_snippet: botMessageText ? botMessageText.substring(0, 250) : null,
                    user_query_that_led_to_this_response: userQuery || null
                })
            });

            if (response.ok) {
                notificationService.showSuccess("Thank you for your feedback!");
                setFeedbackSent(prev => ({ ...prev, [messageId]: rating === 1 ? 'up' : 'down' }));
            } else {
                const errorData = await response.json().catch(() => ({ detail: "Failed to submit feedback." }));
                notificationService.showError(`Feedback error: ${errorData.detail || response.statusText}`);
            }
        } catch (error) {
            notificationService.showError(`Feedback submission error: ${error.message}`);
        }
    };

    return (
        <div style={chatWindowStyle} className="chat-window-container">
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px'}}>
                <p style={{fontSize: '0.8em', color: 'gray', margin: 0}}>
                    Session ID: {currentSessionId}
                </p>
                <button onClick={handleClearChat} disabled={isLoading} style={{...buttonStyle, backgroundColor: '#f0f0f0', fontSize: '0.9em'}}>
                    Clear Chat
                </button>
            </div>
            <div style={messagesAreaStyle} className="messages-area">
                {messages.map((msg, index) => { // Added index for finding previous message
                    let content = <p>{msg.text}</p>; // Default for text messages

                    if (msg.type === 'code' && msg.raw_response?.generated_code) {
                        // msg.text might be a preamble like "Here's the code:"
                        // msg.raw_response.generated_code has the actual code.
                        content = (
                            <>
                                {msg.text && <p>{msg.text}</p>}
                                <pre style={codeBlockStyle}><code>{msg.raw_response.generated_code}</code></pre>
                            </>
                        );
                    } else if (msg.type === 'error') { // Explicit error type styling
                        content = <p>{msg.text}</p>; // Style applied via messageStyle
                    }


                    return (
                        <div key={msg.id} style={messageStyle(msg.sender === 'user', msg.type)} className={`message ${msg.sender} message-type-${msg.type}`}>
                            {content}
                            {/* Render structured tool data if available, in addition to msg.text (summary) */}
                            {msg.sender === 'bot' && msg.type !== 'error' && msg.raw_response?.structured_tool_data && (
                                <div className="structured-tool-data" style={{marginTop: '10px'}}>
                                    {msg.raw_response.tool_data_type === 'news_articles' &&
                                        <NewsDisplay articles={msg.raw_response.structured_tool_data} />}
                                    {msg.raw_response.tool_data_type === 'earnings_reports' &&
                                        <EarningsDisplay reports={msg.raw_response.structured_tool_data} />}
                                    {/* Add more conditions for other tool_data_types here as needed */}
                                </div>
                            )}
                            {/* Feedback Buttons for bot messages (non-error) */}
                            {msg.sender === 'bot' && msg.type !== 'error' && (
                                <div className="feedback-buttons" style={{ marginTop: '8px', textAlign: 'right' }}>
                                    {!feedbackSent[msg.id] ? (
                                        <>
                                            <button
                                                onClick={() => {
                                                    const prevUserMsg = messages[index-1]?.sender === 'user' ? messages[index-1].text : "Unknown";
                                                    handleFeedback(msg.id, msg.text, prevUserMsg, 1);
                                                }}
                                                title="Helpful"
                                                style={{background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2em'}}>👍</button>
                                            <button
                                                onClick={() => {
                                                    const prevUserMsg = messages[index-1]?.sender === 'user' ? messages[index-1].text : "Unknown";
                                                    handleFeedback(msg.id, msg.text, prevUserMsg, -1);
                                                }}
                                                title="Not Helpful"
                                                style={{background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2em', marginLeft: '8px'}}>👎</button>
                                        </>
                                    ) : (
                                        <span style={{fontSize: '0.9em', color: feedbackSent[msg.id] === 'up' ? 'green' : 'orange' }}>
                                            Feedback {feedbackSent[msg.id] === 'up' ? 'sent (👍)' : 'sent (👎)'}
                                        </span>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}
                <div ref={messagesEndRef} />
            </div>
            {/* Combined input area with form for send */}
            {/* The clear button is moved above messages area for better UX */}
            <form onSubmit={handleSendMessage} style={{...inputAreaStyle, display: 'flex', flexGrow: 1}}>
                 <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Type your message or /code Your strategy request..."
                    disabled={isLoading}
                    style={inputStyle}
                />
                <button type="submit" disabled={isLoading} style={buttonStyle}>
                    {isLoading ? 'Sending...' : 'Send'}
                </button>
            </form>
        </div>
    );
}
export default ChatWindow;

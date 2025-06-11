// webapp/frontend/src/components/ChatWindow.js
import React, { useState, useEffect, useRef } from 'react';
import notificationService from '../services/notificationService'; // Assuming this exists

// Basic styling (can be moved to a CSS file)
const chatWindowStyle = { border: '1px solid #ccc', padding: '10px', height: '500px', display: 'flex', flexDirection: 'column', marginTop: '20px' };
const messagesAreaStyle = { flexGrow: 1, overflowY: 'auto', marginBottom: '10px', borderBottom: '1px solid #eee', paddingRight: '10px' };
const messageStyle = (isUser) => ({
    textAlign: isUser ? 'right' : 'left',
    margin: '5px',
    padding: '8px 12px',
    borderRadius: '10px',
    backgroundColor: isUser ? '#dcf8c6' : '#f1f0f0',
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

            if (!response.ok) {
                const errorDetail = data.detail || data.error_message || data.error?.message || 'Chat API request failed';
                notificationService.showError(`Chat Error: ${errorDetail}`);
                setMessages(prev => [...prev, {id: `bot_err_${Date.now()}`, text: `Error: ${errorDetail}`, sender: 'bot', type: 'error'}]);
                return;
            }

            if (data.session_id && data.session_id !== currentSessionId) {
                setCurrentSessionId(data.session_id);
            }

            let botResponseText = data.response_text;
            let botMessageType = 'text';
            let toolData = null;

            if (data.generated_code) {
                botMessageType = 'code';
                botResponseText = data.generated_code; // Just the code for the 'text' part of the message
            } else if (data.tool_used && data.tool_response) {
                botMessageType = 'tool_response';
                botResponseText = `Tool Used: ${data.tool_used}\nResponse:\n${data.tool_response}`;
                toolData = {name: data.tool_used, response: data.tool_response};
            }

            if (data.rag_context_used && botMessageType !== 'code') { // Don't prepend to code block itself
                 botResponseText = "[Using Knowledge Base]\n" + botResponseText;
            }

            // For code, response_text might be an intro like "Here's the code:"
            // We use generated_code directly for the 'text' field if type is 'code'.
            // If not code, but there's an intro in response_text and also tool/rag, prepend.
            let displayResponseText = botResponseText;
            if (botMessageType === 'code' && data.response_text && data.response_text.toLowerCase().includes("generated python code")) {
                displayResponseText = data.response_text + "\n" + botResponseText;
            }


            const botMessage = {
                id: `bot_${Date.now()}`,
                text: displayResponseText,
                sender: 'bot',
                type: botMessageType,
                tool_data: toolData,
                raw_response: data
            };
            setMessages(prev => [...prev, botMessage]);

        } catch (error) {
            setIsLoading(false);
            notificationService.showError(`Failed to send message: ${error.message}`);
            setMessages(prev => [...prev, {id: `catch_err_${Date.now()}`, text: `Error: ${error.message}`, sender: 'bot', type: 'error'}]);
        }
    };

    const renderMessageContent = (msg) => {
        if (msg.type === 'code') {
            // If the message text itself contains the "Here's the code..." preamble, extract just the code.
            // Otherwise, assume msg.text is purely the code.
            const codeRegex = /```python\n([\s\S]*?)\n```/;
            const match = msg.text.match(codeRegex);
            const codeContent = match ? match[1] : msg.text; // Fallback to full text if no explicit block

            let preamble = "";
            if (match && msg.text.substring(0, match.index).trim()) {
                 preamble = <p>{msg.text.substring(0, match.index).trim()}</p>;
            } else if (!match && msg.raw_response?.response_text?.toLowerCase().includes("generated python code")) {
                 preamble = <p>{msg.raw_response.response_text}</p>;
            }


            return <> {preamble} <pre style={codeBlockStyle}><code>{codeContent}</code></pre> </>;
        }
        // For other types, just display the text. Could be enhanced for markdown.
        return <p>{msg.text}</p>;
    };


    return (
        <div style={chatWindowStyle} className="chat-window-container">
            <div style={messagesAreaStyle} className="messages-area">
                {messages.map(msg => (
                    <div key={msg.id} style={messageStyle(msg.sender === 'user')} className={`message ${msg.sender} message-type-${msg.type}`}>
                        {renderMessageContent(msg)}
                    </div>
                ))}
                <div ref={messagesEndRef} />
            </div>
            <form onSubmit={handleSendMessage} style={inputAreaStyle} className="input-area">
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

// webapp/frontend/src/components/MessageItem.js
import React, { useState } from 'react'; // Import useState
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { python } from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism'; // A popular light theme

// It's generally recommended to register languages outside the component rendering path,
// but for PrismAsyncLight, importing the language and specifying its name as a string
// in the component prop is often sufficient for dynamic loading.
// If issues arise, explicit registration might be needed:
// SyntaxHighlighter.registerLanguage('python', python);

const MessageItem = ({ message }) => {
  const isUser = message.sender === 'user';
  const [copied, setCopied] = useState(false); // State for copy feedback

  const handleCopyCode = () => {
    if (message.code) {
      navigator.clipboard.writeText(message.code)
        .then(() => {
          setCopied(true);
          setTimeout(() => {
            setCopied(false);
          }, 2000); // Reset feedback after 2 seconds
        })
        .catch(err => {
          console.error('Failed to copy code: ', err);
          // Optionally, display an error message to the user here
        });
    }
  };

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

  // Custom style for the <pre> tag rendered by SyntaxHighlighter
  const syntaxHighlighterCustomStyle = {
    borderRadius: '6px', // Rounded corners for the code block itself
    padding: '10px',    // Internal padding of the code block
    fontSize: '0.85em',  // Slightly smaller font for code
    // The 'tomorrow' style itself will define background and text colors.
    // If override is needed: backgroundColor: '#f5f5f5', // A neutral light grey
  };

  return (
    <div style={messageStyle}>
      <div style={bubbleStyle}>
        {message.text && message.text.trim() !== '' && (
          <div style={{ whiteSpace: 'pre-wrap', marginBottom: message.code ? '10px' : '0' }}>
            {/* Add margin-bottom only if code is present */}
            {message.text}
          </div>
        )}
        {message.code && (
          <div style={{
            position: 'relative',
            marginTop: message.text && message.text.trim() !== '' ? '10px' : '0',
          }}>
            <button
              onClick={handleCopyCode}
              style={{
                position: 'absolute',
                top: '8px', // Adjust as needed based on padding of SyntaxHighlighter
                right: '8px', // Adjust as needed
                zIndex: 1,
                padding: '4px 8px',
                fontSize: '0.75em', // Smaller font for a small button
                backgroundColor: copied ? '#28a745' : '#6c757d', // Green when copied
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                opacity: 0.9,
              }}
              // disabled={copied} // Optional: disable button briefly
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
            <SyntaxHighlighter
              language="python"
              style={tomorrow}
              customStyle={{
                ...syntaxHighlighterCustomStyle, // Spread existing custom styles
                paddingTop: '35px', // Ensure space for the button if it's inside the <pre> padding area
              }}
              codeTagProps={{
                style: {
                  fontFamily: '"Fira Code", "Operator Mono", "Consolas", "Menlo", "Monaco", monospace',
                }
              }}
              showLineNumbers={false}
              wrapLines={true}
              lineProps={{style: {wordBreak: 'break-all', whiteSpace: 'pre-wrap'}}}
            >
              {String(message.code).trim()}
            </SyntaxHighlighter>
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageItem;

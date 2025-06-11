// webapp/frontend/src/services/chatService.js

// Allow backend URL to be configurable via environment variable,
// defaulting for local development.
const LLM_CHATBOT_SERVICE_URL = process.env.REACT_APP_LLM_CHATBOT_SERVICE_URL || 'http://localhost:8001';

/**
 * Sends a message to the LLM chatbot backend.
 * @param {string} message - The user's message.
 * @param {string} sessionId - The current chat session ID.
 * @param {string} userId - The user ID (can be a mock ID for now).
 * @returns {Promise<object>} - A promise that resolves to the backend's JSON response.
 * @throws {Error} - Throws an error if the API call fails or returns a non-ok response.
 */
export const sendMessageToBot = async (message, sessionId, userId = 'frontend_user_01') => {
  const endpoint = `${LLM_CHATBOT_SERVICE_URL}/chat`;

  const payload = {
    user_id: userId,
    message: message,
    session_id: sessionId,
  };

  console.log(`Sending payload to ${endpoint}:`, payload); // For debugging

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // Add any other headers like Authorization if the LLM service requires them in the future
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      // Try to parse error response from backend if available
      let errorData;
      try {
        errorData = await response.json();
        console.error('Backend error response:', errorData); // For debugging
      } catch (e) {
        // Ignore if error response is not JSON
        console.error('Non-JSON error response:', await response.text()); // For debugging
        errorData = { detail: `HTTP error! status: ${response.status}` };
      }
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    // Log the full error object, not just error.message, for more details in browser console
    console.error('Error sending message to bot:', error);
    // Re-throw the error so the component can catch it and set its error state
    // If it's a network error, error.message will be like "Failed to fetch"
    // If it's an error we threw due to bad HTTP status, it will be our custom message
    throw error;
  }
};

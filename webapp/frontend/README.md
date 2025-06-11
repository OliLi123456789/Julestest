# Webapp Frontend

This directory contains the React-based frontend for the trading platform application.

## Features

*   User Authentication (Login Form)
*   Trading Dashboard:
    *   Chart Display
    *   Order Entry Form
    *   Orders View
*   AI Assistant Chat Mode

## Getting Started

### Prerequisites

*   Node.js and npm (or yarn)
*   Access to the backend services (main application backend, LLM Chatbot Service)

### Installation

1.  Navigate to the `webapp/frontend` directory.
2.  Install dependencies:
    ```bash
    npm install
    # or
    # yarn install
    ```

### Running Locally

1.  Ensure the backend services are running and accessible.
2.  The `llm_chatbot_service` URL can be configured via the `REACT_APP_LLM_CHATBOT_SERVICE_URL` environment variable in a `.env` file in this directory (e.g., `REACT_APP_LLM_CHATBOT_SERVICE_URL=http://localhost:8001`). If not set, it defaults to `http://localhost:8001`.
3.  Start the development server:
    ```bash
    npm start
    # or
    # yarn start
    ```
4.  The application will typically open in your browser at `http://localhost:3000`.

## AI Assistant Chat Mode

The application includes an "AI Assistant Chat Mode" that allows users to interact with an LLM-powered chatbot.

### Accessing Chat Mode

1.  After logging into the application, you will see the main trading dashboard.
2.  In the header, click the button labeled "AI Chat View" (or similar).
3.  This will switch the view to the AI Assistant Chat interface.
4.  To return to the trading dashboard, click the button again (it might be labeled "Trading View").

### Features

*   **Interactive Chat**: Send messages to the AI assistant and receive responses.
*   **Session Management**: Each chat session is unique (identified by a session ID internally).
*   **Loading & Error States**: The interface provides feedback when the assistant is processing a request or if an error occurs.
*   **Backend Integration**: Communicates with the `llm_chatbot_service` to leverage its LLM, RAG, and Tool capabilities.
*   **Code Generation (`/code` command)**:
    *   You can ask the AI Assistant to generate code snippets by prefixing your request with the `/code` command.
    *   **Example**: `/code python function to calculate factorial`
    *   **Display**: Generated code will be displayed in a formatted block within the chat message.
    *   **Syntax Highlighting**: Code snippets are automatically syntax-highlighted (primarily for Python) for better readability.
    *   **Copy to Clipboard**: A "Copy" button is provided with each code block, allowing you to easily copy the generated code.

### Using the Chat

*   Type your message in the input field at the bottom of the chat window.
*   Click "Send" or press Enter to submit your message.
*   The assistant's response will appear in the chat history.

## Available Scripts

In the project directory, you can run:

*   `npm start` / `yarn start`: Runs the app in development mode.
*   `npm test` / `yarn test`: Launches the test runner in interactive watch mode. (Includes unit tests for components like `MessageInput.js`).
*   `npm run build` / `yarn build`: Builds the app for production to the `build` folder.
*   `npm run eject` / `yarn eject`: (Advanced) Removes the single-file dependency configuration.

import React, { useState } from 'react';
import { notificationService } from '../services/notificationService'; // Import notificationService

function LoginForm({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(''); // Keep local error for inline display if needed

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null); // Clear previous errors

    // FastAPI's OAuth2PasswordRequestForm expects x-www-form-urlencoded
    const formBody = new URLSearchParams();
    formBody.append('username', username);
    formBody.append('password', password);

    try {
        const response = await fetch('/auth/token', { // Adjust URL if needed for dev (e.g., http://localhost:8000/auth/token)
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formBody.toString(),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Login failed. Please check your credentials.');
        }

        if (data.access_token) {
            notificationService.showSuccess("Login successful!");
            onLogin(data.access_token);
        } else {
            // This case might be redundant if !response.ok already caught it
            throw new Error('Login failed: No access token received.');
        }
    } catch (err) {
        const errorMessage = err.message || 'Login failed. Please check your credentials.';
        setError(errorMessage); // Set local error state for display within the form
        notificationService.showError(errorMessage); // Show toast notification
        console.error("Login error:", err);
    }
  };

  return (
    <div>
      <h2>Login</h2>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">Username:</label>
          <input
            type="text"
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="password">Password:</label>
          <input
            type="password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <p style={{ color: 'red' }}>{error}</p>}
        <button type="submit">Login</button>
      </form>
    </div>
  );
}

export default LoginForm;

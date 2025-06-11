// webapp/frontend/src/components/MessageInput.test.js
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom'; // For extended matchers like .toBeDisabled()
import MessageInput from './MessageInput';

describe('MessageInput Component', () => {
  test('renders input field and send button', () => {
    render(<MessageInput onSendMessage={() => {}} isLoading={false} />);

    expect(screen.getByPlaceholderText('Type your message...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  test('allows user to type in the input field', () => {
    render(<MessageInput onSendMessage={() => {}} isLoading={false} />);
    const inputElement = screen.getByPlaceholderText('Type your message...');

    fireEvent.change(inputElement, { target: { value: 'Hello there' } });
    expect(inputElement.value).toBe('Hello there');
  });

  test('calls onSendMessage with the input value when send button is clicked', () => {
    const mockOnSendMessage = jest.fn();
    render(<MessageInput onSendMessage={mockOnSendMessage} isLoading={false} />);
    const inputElement = screen.getByPlaceholderText('Type your message...');
    const sendButton = screen.getByRole('button', { name: /send/i });

    fireEvent.change(inputElement, { target: { value: 'Test message' } });
    fireEvent.click(sendButton);

    expect(mockOnSendMessage).toHaveBeenCalledTimes(1);
    expect(mockOnSendMessage).toHaveBeenCalledWith('Test message');
    expect(inputElement.value).toBe(''); // Input should clear after sending
  });

  test('calls onSendMessage when Enter key is pressed in input field (form submission)', () => {
    const mockOnSendMessage = jest.fn();
    render(<MessageInput onSendMessage={mockOnSendMessage} isLoading={false} />);
    const inputElement = screen.getByPlaceholderText('Type your message...');
    const formElement = inputElement.closest('form'); // Get the form

    fireEvent.change(inputElement, { target: { value: 'Enter message' } });
    fireEvent.submit(formElement); // Simulate form submission

    expect(mockOnSendMessage).toHaveBeenCalledTimes(1);
    expect(mockOnSendMessage).toHaveBeenCalledWith('Enter message');
    expect(inputElement.value).toBe('');
  });

  test('does not call onSendMessage if input is empty or only whitespace', () => {
    const mockOnSendMessage = jest.fn();
    render(<MessageInput onSendMessage={mockOnSendMessage} isLoading={false} />);
    const inputElement = screen.getByPlaceholderText('Type your message...');
    const sendButton = screen.getByRole('button', { name: /send/i });

    // Test with empty input
    fireEvent.click(sendButton);
    expect(mockOnSendMessage).not.toHaveBeenCalled();

    // Test with whitespace input
    fireEvent.change(inputElement, { target: { value: '   ' } });
    fireEvent.click(sendButton);
    expect(mockOnSendMessage).not.toHaveBeenCalled();
    expect(inputElement.value).toBe('   '); // Input should not clear if message not sent
  });

  test('disables input and button when isLoading is true', () => {
    render(<MessageInput onSendMessage={() => {}} isLoading={true} />);

    expect(screen.getByPlaceholderText('Type your message...')).toBeDisabled();
    // Check for the button by its role and new text "Sending..."
    expect(screen.getByRole('button', { name: /sending.../i })).toBeDisabled();
  });

  test('button text changes to "Sending..." when isLoading is true', () => {
    render(<MessageInput onSendMessage={() => {}} isLoading={true} />);
    expect(screen.getByRole('button', { name: /sending.../i })).toBeInTheDocument();
    // Also check that the "Send" button is not present
    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument();
  });
});

// webapp/frontend/src/components/ErrorBoundary.js
import React from 'react';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, errorInfo: null };
    }

    static getDerivedStateFromError(error) {
        // Update state so the next render will show the fallback UI.
        return { hasError: true };
    }

    componentDidCatch(error, errorInfo) {
        // You can also log the error to an error reporting service
        console.error("ErrorBoundary caught an error:", error, errorInfo);
        this.setState({ error: error, errorInfo: errorInfo });
    }

    render() {
        if (this.state.hasError) {
            // You can render any custom fallback UI
            return (
                <div style={{ padding: '20px', border: '1px solid red', margin: '10px', backgroundColor: '#fff0f0' }}>
                    <h4>Something went wrong in this section.</h4>
                    <p>An unexpected error occurred. Please try refreshing or check back later.</p>
                    {/*
                    // For development, you might want to display the error:
                    // We can use a prop to conditionally display this, e.g., this.props.isDevelopment
                    // For now, let's assume isDevelopment is true for easier debugging if needed.
                    // In a production build, this would ideally be false.
                    */}
                    {process.env.NODE_ENV === 'development' && this.state.error && (
                        <details style={{ whiteSpace: 'pre-wrap', marginTop: '10px' }}>
                            <summary>Error Details (Development Mode)</summary>
                            {this.state.error.toString()}
                            <br />
                            {this.state.errorInfo?.componentStack}
                        </details>
                    )}
                </div>
            );
        }
        return this.props.children;
    }
}
export default ErrorBoundary;

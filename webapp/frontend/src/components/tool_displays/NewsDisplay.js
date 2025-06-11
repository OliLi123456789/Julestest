// webapp/frontend/src/components/tool_displays/NewsDisplay.js
import React from 'react';

// Basic styling - can be moved to CSS
const newsDisplayContainerStyle = {
    borderTop: '1px dashed #ddd',
    marginTop: '10px',
    paddingTop: '10px'
};
const newsItemStyle = {
    border: '1px solid #eee',
    padding: '10px',
    marginBottom: '10px',
    borderRadius: '5px',
    backgroundColor: '#f9f9f9'
};
const titleStyle = { fontWeight: 'bold', marginBottom: '5px', fontSize: '1.1em' };
const sourceStyle = { fontSize: '0.9em', color: '#555', marginBottom: '3px' };
const sentimentStyle = (score) => ({
    fontWeight: 'bold',
    color: score > 0.1 ? 'green' : score < -0.1 ? 'red' : 'gray', // Basic coloring
});

function NewsDisplay({ articles }) { // articles is List[NewsArticleResponse]
    if (!articles || articles.length === 0) {
        return <p>No news articles to display.</p>;
    }

    return (
        <div style={newsDisplayContainerStyle} className="news-display-container">
            <h5 style={{ marginTop: '0', marginBottom: '10px' }}>News Articles:</h5>
            {articles.map((article, index) => (
                <div key={article.id || article.url || index} style={newsItemStyle}>
                    <p style={titleStyle}>
                        <a href={article.url} target="_blank" rel="noopener noreferrer">
                            {article.title || "N/A"}
                        </a>
                    </p>
                    <p style={sourceStyle}>
                        Source: {article.source_name || article.source?.name || "N/A"} |
                        Published: {article.published_at ? new Date(article.published_at).toLocaleDateString() : "N/A"}
                    </p>
                    {article.description && <p>{article.description}</p>}
                    {article.sentiment_score_compound !== null && article.sentiment_score_compound !== undefined && (
                        <p style={sentimentStyle(article.sentiment_score_compound)}>
                            Sentiment (Compound): {article.sentiment_score_compound.toFixed(2)}
                        </p>
                    )}
                </div>
            ))}
        </div>
    );
}
export default NewsDisplay;

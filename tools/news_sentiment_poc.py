import nltk
import json
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# --- Mock NewsAPI Response ---
# This simulates what we might get from newsapi.org for a specific ticker.
MOCK_NEWS_RESPONSE = {
    "status": "ok",
    "totalResults": 3,
    "articles": [
        {
            "source": {"id": "reuters", "name": "Reuters"},
            "author": "John Doe",
            "title": "BigTechCorp (BTC) Announces Record Profits for Q3!",
            "description": "BigTechCorp today reported quarterly earnings that beat analyst expectations, sending its stock soaring. CEO Jane Smith highlighted strong cloud growth.",
            "url": "https://www.reuters.com/article/idUSKBN2RT28S",
            "urlToImage": "https://www.reuters.com/resizer/dummy.jpg",
            "publishedAt": "2023-10-27T10:00:00Z",
            "content": "NEW YORK, Oct 27 (Reuters) - BigTechCorp (BTC) on Friday reported record third-quarter profits that surpassed Wall Street estimates, driven by robust growth in its cloud computing division. The company's shares jumped 8% in premarket trading..."
        },
        {
            "source": {"id": "bloomberg", "name": "Bloomberg"},
            "author": "Emily Carter",
            "title": "Analysts Concerned Over BigTechCorp's (BTC) Increased Spending",
            "description": "Despite strong Q3 earnings, some analysts expressed concerns over BigTechCorp's rising operational costs and R&D expenditure, questioning future margin sustainability.",
            "url": "https://www.bloomberg.com/news/articles/2023-10-27/btc-earnings-q3",
            "urlToImage": "https://assets.bwbx.io/images/users/dummy.jpg",
            "publishedAt": "2023-10-27T11:30:00Z",
            "content": "BigTechCorp's (BTC) otherwise stellar earnings report was tempered by a notable increase in operating expenses and research and development costs, according to its latest financial disclosures..."
        },
        {
            "source": {"id": "techcrunch", "name": "TechCrunch"},
            "author": "Alex Wilhelm",
            "title": "BigTechCorp (BTC) Debuts New AI Product Line, Market Lukewarm",
            "description": "The much-anticipated launch of BigTechCorp's new AI-powered gadgets received a mixed reaction from the market, with experts citing high prices and unclear utility.",
            "url": "https://techcrunch.com/2023/10-27/btc-new-ai-products/",
            "urlToImage": "https://techcrunch.com/wp-content/uploads/dummy.png",
            "publishedAt": "2023-10-27T14:00:00Z",
            "content": "Today, BigTechCorp (BTC) unveiled its new 'AI-Verse' product line. While the technology is impressive, the initial market response has been lukewarm, possibly due to premium pricing and questions around immediate consumer benefit..."
        }
    ]
}

def download_nltk_vader_if_needed():
    """Checks if VADER lexicon is downloaded, if not, downloads it."""
    try:
        nltk.data.find('sentiment/vader_lexicon.zip')
        print("NLTK VADER lexicon found.")
    except LookupError: # Correctly catch the resource not found error
        print("NLTK VADER lexicon not found (LookupError). Downloading...")
        nltk.download('vader_lexicon')
        print("NLTK VADER lexicon downloaded successfully.")
    except Exception as e: # Catch other potential errors during find or download
        print(f"An error occurred (e.g., network issue during download): {e}. Attempting download.")
        nltk.download('vader_lexicon') # Try downloading anyway
        print("NLTK VADER lexicon download attempt finished.")


def analyze_sentiment(text: str) -> dict:
    """
    Analyzes the sentiment of a given text using NLTK VADER.
    Returns a dictionary with neg, neu, pos, compound scores.
    """
    analyzer = SentimentIntensityAnalyzer()
    sentiment_scores = analyzer.polarity_scores(text)
    return sentiment_scores

def fetch_and_analyze_news(symbol: str):
    """
    Mocks fetching news for a symbol and analyzes sentiment of headlines and descriptions.
    """
    print(f"\n--- News Sentiment for {symbol} (Mocked) ---")

    # In a real scenario, you would make an API call here:
    # response = requests.get(f"https://newsapi.org/v2/everything?q={symbol}&apiKey=YOUR_API_KEY")
    # articles = response.json().get("articles", [])
    articles = MOCK_NEWS_RESPONSE.get("articles", [])

    if not articles:
        print(f"No news articles found for {symbol}.")
        return

    for article in articles:
        title = article.get("title", "")
        description = article.get("description", "")
        source_name = article.get("source", {}).get("name", "N/A")
        published_at = article.get("publishedAt", "N/A")

        print(f"\nHeadline: {title}")
        print(f"Source: {source_name}, Published: {published_at}")
        # print(f"Description: {description}")

        # Analyze sentiment of title + description for better context
        text_to_analyze = title + ". " + description if description else title

        if text_to_analyze.strip(): # Ensure there's text to analyze
            sentiment = analyze_sentiment(text_to_analyze)
            print(f"Sentiment (VADER): {sentiment}")
            # Interpretation of compound score:
            # Positive: compound score >= 0.05
            # Neutral: compound score > -0.05 and < 0.05
            # Negative: compound score <= -0.05
            compound = sentiment.get('compound', 0)
            if compound >= 0.05:
                print("Overall Sentiment: Positive")
            elif compound <= -0.05:
                print("Overall Sentiment: Negative")
            else:
                print("Overall Sentiment: Neutral")
        else:
            print("No text content to analyze for sentiment.")

    print("\n--- End of News Sentiment Analysis ---")

if __name__ == "__main__":
    print("Starting News Sentiment PoC script...")
    download_nltk_vader_if_needed()
    fetch_and_analyze_news(symbol="BigTechCorp (BTC)") # Using the symbol from mock data
    print("\nNews Sentiment PoC script finished.")

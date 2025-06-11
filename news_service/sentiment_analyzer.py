# news_service/sentiment_analyzer.py
import nltk
import logging
from typing import Dict, Optional, Any # Added Any

logger = logging.getLogger(__name__)
_vader_analyzer_instance: Optional[Any] = None # Using Any for SentimentIntensityAnalyzer to avoid import error if nltk fails
_vader_downloaded = False

def download_nltk_vader_if_needed(force_download: bool = False) -> bool:
    """
    Checks if NLTK VADER lexicon is available and downloads it if not.
    Returns True if VADER is available or successfully downloaded, False otherwise.
    """
    global _vader_downloaded
    if _vader_downloaded and not force_download:
        logger.debug("NLTK VADER lexicon already marked as available.")
        return True

    try:
        # nltk.data.find will raise LookupError if not found.
        nltk.data.find('sentiment/vader_lexicon.zip')
        logger.info("NLTK VADER lexicon found locally.")
        _vader_downloaded = True
        return True
    except LookupError:
        logger.info("NLTK VADER lexicon not found locally. Attempting download...")
        try:
            nltk.download('vader_lexicon')
            # Verify download
            nltk.data.find('sentiment/vader_lexicon.zip') # Will raise LookupError again if download failed silently
            logger.info("NLTK VADER lexicon downloaded successfully.")
            _vader_downloaded = True
            return True
        except Exception as e_download:
            # This could be a download error, or the find after download failed.
            logger.error(f"Failed to download or verify NLTK VADER lexicon: {e_download}", exc_info=True)
            _vader_downloaded = False
            return False
    except Exception as e_find: # Catch other potential errors during the find process (e.g., network issues if nltk.data.find does more)
        logger.error(f"An unexpected error occurred while checking for VADER lexicon: {e_find}. Attempting download as a fallback.", exc_info=True)
        try:
            nltk.download('vader_lexicon')
            nltk.data.find('sentiment/vader_lexicon.zip')
            logger.info("NLTK VADER lexicon downloaded successfully after initial find error.")
            _vader_downloaded = True
            return True
        except Exception as e_download_retry:
            logger.error(f"Retry download of NLTK VADER lexicon failed: {e_download_retry}", exc_info=True)
            _vader_downloaded = False
            return False

class SentimentAnalyzer:
    def __init__(self):
        global _vader_analyzer_instance
        self.analyzer: Optional[Any] = None # Using Any for SentimentIntensityAnalyzer

        if not _vader_downloaded: # Check if already marked as downloaded
            if not download_nltk_vader_if_needed(): # Attempt download if not
                logger.error("SentimentAnalyzer: VADER lexicon is unavailable. Sentiment analysis will not work.")
                return # self.analyzer remains None

        # Initialize the analyzer instance if VADER is available
        if _vader_downloaded:
            if _vader_analyzer_instance is None: # Singleton pattern for the analyzer
                try:
                    from nltk.sentiment.vader import SentimentIntensityAnalyzer
                    _vader_analyzer_instance = SentimentIntensityAnalyzer()
                    logger.info("SentimentIntensityAnalyzer (VADER) initialized successfully.")
                except Exception as e_init: # Catch potential errors during VADER init
                    logger.error(f"Failed to initialize SentimentIntensityAnalyzer: {e_init}", exc_info=True)
                    # Ensure _vader_downloaded might be reset if init fails, to allow re-attempt
                    # global _vader_downloaded # Not strictly needed here as we are just logging error
                    # _vader_downloaded = False # Or some other state to indicate failure
                    return # self.analyzer remains None
            self.analyzer = _vader_analyzer_instance
        else:
            logger.error("SentimentAnalyzer: VADER lexicon not downloaded/found. Analyzer not available.")


    def analyze_sentiment(self, text: Optional[str]) -> Optional[Dict[str, float]]:
        if not self.analyzer:
            logger.error("VADER Analyzer not initialized. Cannot analyze sentiment.")
            return None
        if not text or not text.strip():
            logger.debug("No text provided for sentiment analysis. Returning None.")
            return None # Or return neutral: {'neg': 0.0, 'neu': 1.0, 'pos': 0.0, 'compound': 0.0}

        try:
            scores = self.analyzer.polarity_scores(text)
            return scores # Expected: {'neg': 0.0, 'neu': 0.0, 'pos': 0.0, 'compound': 0.0}
        except Exception as e:
            logger.error(f"Sentiment analysis failed for text snippet '{text[:100]}...': {e}", exc_info=True)
            return None

if __name__ == '__main__':
    # Setup basic logging for the __main__ example
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')

    logger_main = logging.getLogger(__name__) # Get logger for this block

    logger_main.info("Attempting to ensure VADER lexicon is available...")
    # First call ensures download if needed, or verifies presence.
    vader_ready = download_nltk_vader_if_needed()

    if vader_ready:
        logger_main.info("VADER lexicon is available. Initializing SentimentAnalyzer...")
        analyzer = SentimentAnalyzer()
        if analyzer.analyzer: # Check if analyzer was successfully initialized
            logger_main.info("SentimentAnalyzer initialized.")
            test_texts = [
                ("This is great news for the company!", "Positive"),
                ("The company reported a huge loss and stock is plummeting.", "Negative"),
                ("The report was as expected, with no major surprises.", "Neutral"),
                ("Despite some concerns, the overall outlook remains positive thanks to new innovations.", "Positive"),
                ("Uncertainty looms over the sector.", "Negative/Neutral"), # VADER might be more nuanced
                ("", "None/Neutral"),
                ("   ", "None/Neutral"),
                (None, "None")
            ]
            for text, expected_sentiment_category in test_texts:
                sentiment_scores = analyzer.analyze_sentiment(text)
                logger_main.info(f"Sentiment for '{text}': {sentiment_scores} (Expected category: ~{expected_sentiment_category})")
        else:
            logger_main.error("Failed to initialize SentimentAnalyzer even after VADER download check.")
    else:
        logger_main.error("VADER lexicon could not be made available. Sentiment analysis tests cannot run.")

    logger_main.info("SentimentAnalyzer example finished.")

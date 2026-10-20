"""
Functions to extract first and last contentful sentences from web articles.
Uses Firecrawl for web scraping and OpenAI for intelligent content extraction.
"""

from typing import Dict, Optional
from firecrawl import FirecrawlApp
from openai import OpenAI

# Import utilities
from config import Config
from logger import get_logger

logger = get_logger(__name__)


def scrape_url_to_markdown(url: str) -> Dict[str, str]:
    """
    Scrape a URL using Firecrawl and convert it to markdown.

    Args:
        url: The URL to scrape

    Returns:
        Dictionary containing:
        - 'markdown': The markdown content of the page
        - 'url': The original URL
        - 'title': Page title (if available)

    Raises:
        ValueError: If FIRECRAWL_API_KEY is not set in environment
        Exception: If scraping fails
    """
    # Get API key from config
    api_key = Config.get_firecrawl_key()
    if not api_key:
        raise ValueError(
            "FIRECRAWL_API_KEY not found in environment variables. "
            "Please add it to your .env file."
        )

    # Initialize Firecrawl
    firecrawl = FirecrawlApp(api_key=api_key)

    try:
        logger.info(f"Scraping URL with Firecrawl: {url}")
        # Scrape the URL and get markdown
        result = firecrawl.scrape_url(url, params={'formats': ['markdown']})

        markdown_length = len(result.get('markdown', ''))
        logger.debug(f"Retrieved {markdown_length} characters of markdown")

        return {
            'markdown': result.get('markdown', ''),
            'url': url,
            'title': result.get('metadata', {}).get('title', '')
        }
    except Exception as e:
        logger.error(f"Failed to scrape URL with Firecrawl: {e}", exc_info=True)
        raise Exception(f"Failed to scrape URL with Firecrawl: {str(e)}")


def extract_first_and_last_sentences(markdown_content: str) -> Dict[str, str]:
    """
    Extract the first and last contentful sentences from markdown content using OpenAI.

    Args:
        markdown_content: The markdown content to analyze

    Returns:
        Dictionary containing:
        - 'first_sentence': The first contentful sentence
        - 'last_sentence': The last contentful sentence

    Raises:
        ValueError: If OPENAI_API_KEY is not set in environment
        Exception: If OpenAI API call fails
    """
    # Get API key from config
    api_key = Config.get_openai_key()
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found in environment variables. "
            "Please add it to your .env file."
        )

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)

    # Construct the prompt
    prompt = f"""What are the first and last contentful sentences in this article? Exclude any advertisements or notices or superfluous material one finds on a website. I want only what is relevant to the main article being discussed here.

Article content:
{markdown_content}

Please respond in JSON format with the following structure:
{{
    "first_sentence": "...",
    "last_sentence": "..."
}}"""

    try:
        logger.info("Extracting sentences with OpenAI")
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts the first and last meaningful sentences from articles, ignoring ads, headers, footers, and other non-content elements. Always respond with valid JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        # Parse the response
        import json
        result = json.loads(response.choices[0].message.content)

        logger.debug(f"Extracted sentences successfully")

        return {
            'first_sentence': result.get('first_sentence', ''),
            'last_sentence': result.get('last_sentence', '')
        }
    except Exception as e:
        logger.error(f"Failed to extract sentences with OpenAI: {e}", exc_info=True)
        raise Exception(f"Failed to extract sentences with OpenAI: {str(e)}")


def process_url(url: str) -> Dict[str, str]:
    """
    Convenience function to scrape a URL and extract first/last sentences in one call.

    Args:
        url: The URL to process

    Returns:
        Dictionary containing:
        - 'url': The original URL
        - 'title': Page title
        - 'first_sentence': The first contentful sentence
        - 'last_sentence': The last contentful sentence
        - 'markdown': The full markdown content
    """
    # Scrape the URL
    scrape_result = scrape_url_to_markdown(url)

    # Extract sentences
    sentences = extract_first_and_last_sentences(scrape_result['markdown'])

    # Combine results
    return {
        'url': scrape_result['url'],
        'title': scrape_result['title'],
        'first_sentence': sentences['first_sentence'],
        'last_sentence': sentences['last_sentence'],
        'markdown': scrape_result['markdown']
    }


def find_first_and_last_sentences_from_url(url: str, use_firecrawl: bool = True) -> Dict[str, Optional[str]]:
    """
    Complete integration function to extract first and last contentful sentences from a URL.

    This function brings together the full workflow:
    1. Scrapes the URL using Firecrawl to get clean markdown content
    2. Uses OpenAI to intelligently extract the first and last contentful sentences
    3. Returns the sentences for use in content extraction

    This should be called BEFORE main content extraction to identify the boundaries
    of the article content.

    Args:
        url: The URL to process
        use_firecrawl: If True (default), use Firecrawl for scraping.
                      If False, returns empty sentences (allows graceful degradation)

    Returns:
        Dictionary containing:
        - 'first_sentence': The first contentful sentence (or None if failed)
        - 'last_sentence': The last contentful sentence (or None if failed)
        - 'success': Boolean indicating if extraction was successful
        - 'error': Error message if extraction failed (None otherwise)

    Example:
        >>> result = find_first_and_last_sentences_from_url("https://example.com/article")
        >>> if result['success']:
        ...     print(f"First: {result['first_sentence']}")
        ...     print(f"Last: {result['last_sentence']}")
    """
    if not use_firecrawl:
        return {
            'first_sentence': None,
            'last_sentence': None,
            'success': False,
            'error': 'Firecrawl disabled'
        }

    try:
        # Step 1: Scrape the URL with Firecrawl
        logger.info("  → Scraping URL with Firecrawl...")
        scrape_result = scrape_url_to_markdown(url)

        if not scrape_result.get('markdown'):
            return {
                'first_sentence': None,
                'last_sentence': None,
                'success': False,
                'error': 'No markdown content retrieved from Firecrawl'
            }

        logger.info(f"  → Retrieved {len(scrape_result['markdown'])} characters of markdown")

        # Step 2: Extract sentences using OpenAI
        logger.info("  → Extracting first and last sentences with OpenAI...")
        sentences = extract_first_and_last_sentences(scrape_result['markdown'])

        if not sentences.get('first_sentence') or not sentences.get('last_sentence'):
            return {
                'first_sentence': None,
                'last_sentence': None,
                'success': False,
                'error': 'OpenAI did not return valid sentences'
            }

        logger.info(f"  ✓ First sentence: {sentences['first_sentence'][:80]}...")
        logger.info(f"  ✓ Last sentence: {sentences['last_sentence'][:80]}...")

        return {
            'first_sentence': sentences['first_sentence'],
            'last_sentence': sentences['last_sentence'],
            'success': True,
            'error': None
        }

    except ValueError as e:
        # API key missing
        return {
            'first_sentence': None,
            'last_sentence': None,
            'success': False,
            'error': f'Configuration error: {str(e)}'
        }
    except Exception as e:
        # Any other error
        return {
            'first_sentence': None,
            'last_sentence': None,
            'success': False,
            'error': f'Failed to extract sentences: {str(e)}'
        }


# Example usage
if __name__ == "__main__":
    # Example URL - replace with your target URL
    test_url = "https://example.com/article"

    try:
        result = process_url(test_url)
        print(f"Title: {result['title']}")
        print(f"\nFirst sentence: {result['first_sentence']}")
        print(f"\nLast sentence: {result['last_sentence']}")
    except Exception as e:
        print(f"Error: {e}")

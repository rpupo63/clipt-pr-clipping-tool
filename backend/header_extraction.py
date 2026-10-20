#!/usr/bin/env python3
"""
Extract article title and subtitle from HTML with formatting information
"""

from bs4 import BeautifulSoup
import re
import json

# Import utilities
from logger import get_logger

logger = get_logger(__name__)


def _extract_formatting_info(element):
    """
    Extract formatting information from a BeautifulSoup element.
    
    Args:
        element: BeautifulSoup element
        
    Returns:
        dict: Dictionary containing formatting information:
            - text: Text content of element
            - element: The BeautifulSoup element
            - tag: Tag name
            - classes: List of CSS classes
            - id: ID attribute (or None)
            - style: Inline style attribute (or None)
            - formatted_html: HTML string representation
    """
    if element is None:
        return None
    
    # Get text content (strip whitespace)
    text = element.get_text(strip=True)
    
    # Get tag name
    tag = element.name if hasattr(element, 'name') else None
    
    # Get classes
    classes = element.get('class', [])
    if classes and not isinstance(classes, list):
        classes = [classes]
    
    # Get ID
    element_id = element.get('id')
    
    # Get inline style
    style = element.get('style')
    
    # Get formatted HTML
    formatted_html = str(element)
    
    return {
        'text': text,
        'element': element,
        'tag': tag,
        'classes': classes or [],
        'id': element_id,
        'style': style,
        'formatted_html': formatted_html
    }


def _find_title_in_dom(soup):
    """
    Find title in DOM using semantic HTML tags and class/id selectors.
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        BeautifulSoup element or None
    """
    # Strategy 1: Look for h1 tags in article/main content areas
    for selector in ['article h1', 'main h1', '[role="main"] h1', 'body h1']:
        h1 = soup.select_one(selector)
        if h1:
            text = h1.get_text(strip=True)
            # Make sure it's not empty and not too short (likely a real title)
            if text and len(text) > 5:
                return h1
    
    # Strategy 2: Look for elements with title/headline in class or id
    title_patterns = [
        r'title',
        r'headline',
        r'heading',
        r'article-title',
        r'post-title'
    ]
    
    # Search all elements for title-related classes/ids
    for element in soup.find_all(['h1', 'h2', 'div', 'span', 'header']):
        classes = element.get('class', [])
        class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
        element_id = element.get('id', '')
        
        for pattern in title_patterns:
            if (re.search(pattern, class_str, re.IGNORECASE) or 
                re.search(pattern, element_id, re.IGNORECASE)):
                text = element.get_text(strip=True)
                if text and len(text) > 5:
                    return element
    
    # Strategy 3: Just find first h1 in body
    h1 = soup.select_one('body h1')
    if h1:
        text = h1.get_text(strip=True)
        if text and len(text) > 5:
            return h1
    
    return None


def _find_title_in_meta(soup):
    """
    Find title in meta tags (og:title, twitter:title).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        str or None: Title text
    """
    # Check Open Graph title
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        return og_title.get('content')
    
    # Check Twitter card title
    twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
    if twitter_title and twitter_title.get('content'):
        return twitter_title.get('content')
    
    # Check page title tag
    title_tag = soup.find('title')
    if title_tag:
        title_text = title_tag.get_text(strip=True)
        # Remove site name suffix (e.g., " | Vogue")
        title_text = re.sub(r'\s*\|.*$', '', title_text).strip()
        if title_text:
            return title_text
    
    return None


def _find_title_in_structured_data(soup):
    """
    Find title in JSON-LD structured data.
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        str or None: Title text
    """
    # Find all script tags with type="application/ld+json"
    scripts = soup.find_all('script', type='application/ld+json')
    
    for script in scripts:
        try:
            data = json.loads(script.string)
            
            # Handle both single objects and arrays
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        title = item.get('headline') or item.get('name')
                        if title:
                            return title
            elif isinstance(data, dict):
                title = data.get('headline') or data.get('name')
                if title:
                    return title
        except (json.JSONDecodeError, AttributeError):
            continue
    
    return None


def _find_subtitle_in_dom(soup, title_element=None):
    """
    Find subtitle in DOM using semantic HTML tags and class/id selectors.
    
    Args:
        soup: BeautifulSoup object
        title_element: Optional title element to search nearby
        
    Returns:
        BeautifulSoup element or None
    """
    subtitle_patterns = [
        r'subtitle',
        r'dek',
        r'deck',
        r'subheading',
        r'sub-heading',
        r'lead',
        r'summary',
        r'excerpt',
        r'description'
    ]
    
    # Strategy 1: Look for subtitle near the title element
    if title_element:
        # Check next sibling
        next_sibling = title_element.find_next_sibling()
        if next_sibling:
            classes = next_sibling.get('class', [])
            class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
            element_id = next_sibling.get('id', '')
            
            for pattern in subtitle_patterns:
                if (re.search(pattern, class_str, re.IGNORECASE) or 
                    re.search(pattern, element_id, re.IGNORECASE)):
                    text = next_sibling.get_text(strip=True)
                    if text and len(text) > 10:  # Subtitles are usually longer
                        return next_sibling
        
        # Check parent's next sibling (subtitle might be outside title's parent)
        parent = title_element.find_parent()
        if parent:
            next_sibling = parent.find_next_sibling()
            if next_sibling:
                # Look for subtitle patterns in the sibling element
                for element in next_sibling.find_all(['p', 'div', 'h2', 'h3', 'span']):
                    classes = element.get('class', [])
                    class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                    element_id = element.get('id', '')
                    
                    for pattern in subtitle_patterns:
                        if (re.search(pattern, class_str, re.IGNORECASE) or 
                            re.search(pattern, element_id, re.IGNORECASE)):
                            text = element.get_text(strip=True)
                            if text and len(text) > 10:
                                return element
    
    # Strategy 2: Look for h2 tags near article/main content
    for selector in ['article h2', 'main h2', '[role="main"] h2']:
        h2 = soup.select_one(selector)
        if h2:
            text = h2.get_text(strip=True)
            if text and len(text) > 10:
                return h2
    
    # Strategy 3: Look for elements with subtitle/dek in class or id anywhere
    for element in soup.find_all(['p', 'div', 'span', 'h2', 'h3']):
        classes = element.get('class', [])
        class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
        element_id = element.get('id', '')
        
        for pattern in subtitle_patterns:
            if (re.search(pattern, class_str, re.IGNORECASE) or 
                re.search(pattern, element_id, re.IGNORECASE)):
                text = element.get_text(strip=True)
                if text and len(text) > 10:
                    return element
    
    return None


def _find_subtitle_in_meta(soup):
    """
    Find subtitle in meta tags (description, og:description).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        str or None: Subtitle text
    """
    # Check Open Graph description
    og_desc = soup.find('meta', property='og:description')
    if og_desc and og_desc.get('content'):
        return og_desc.get('content')
    
    # Check meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        return meta_desc.get('content')
    
    # Check Twitter description
    twitter_desc = soup.find('meta', attrs={'name': 'twitter:description'})
    if twitter_desc and twitter_desc.get('content'):
        return twitter_desc.get('content')
    
    return None


def _find_subtitle_in_structured_data(soup):
    """
    Find subtitle in JSON-LD structured data (alternativeHeadline, description).
    
    Args:
        soup: BeautifulSoup object
        
    Returns:
        str or None: Subtitle text
    """
    scripts = soup.find_all('script', type='application/ld+json')
    
    for script in scripts:
        try:
            data = json.loads(script.string)
            
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        subtitle = (item.get('alternativeHeadline') or 
                                  item.get('description'))
                        if subtitle:
                            return subtitle
            elif isinstance(data, dict):
                subtitle = (data.get('alternativeHeadline') or 
                          data.get('description'))
                if subtitle:
                    return subtitle
        except (json.JSONDecodeError, AttributeError):
            continue
    
    return None


def extract_headers(html_content: str) -> dict:
    """
    Extract article title and subtitle from HTML with formatting information.
    
    This function searches for titles and subtitles using multiple strategies:
    1. DOM elements (h1, h2, semantic HTML with class/id patterns)
    2. Meta tags (og:title, twitter:title, etc.)
    3. Structured data (JSON-LD)
    
    Args:
        html_content: Full HTML content as string (from site_preprocessing.py)
        
    Returns:
        dict: Dictionary with keys:
            - 'title': dict with text, element, tag, classes, id, style, formatted_html
              (or None if not found)
            - 'subtitle': dict with text, element, tag, classes, id, style, formatted_html
              (or None if not found)
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
    except Exception as e:
        # Return empty structure if HTML parsing fails
        return {'title': None, 'subtitle': None}
    
    title_element = None
    title_info = None
    
    # Try to find title using multiple strategies
    # Strategy 1: DOM elements (preferred - has formatting info)
    title_element = _find_title_in_dom(soup)
    if title_element:
        title_info = _extract_formatting_info(title_element)
    else:
        # Strategy 2: Meta tags (fallback)
        title_text = _find_title_in_meta(soup)
        if not title_text:
            # Strategy 3: Structured data (last resort)
            title_text = _find_title_in_structured_data(soup)
        
        if title_text:
            # Create a minimal structure for meta/structured data titles
            title_info = {
                'text': title_text,
                'element': None,
                'tag': None,
                'classes': [],
                'id': None,
                'style': None,
                'formatted_html': None
            }
    
    # Try to find subtitle using multiple strategies
    subtitle_element = None
    subtitle_info = None
    
    # Strategy 1: DOM elements (preferred - has formatting info)
    subtitle_element = _find_subtitle_in_dom(soup, title_element)
    if subtitle_element:
        subtitle_info = _extract_formatting_info(subtitle_element)
    else:
        # Strategy 2: Meta tags (fallback)
        subtitle_text = _find_subtitle_in_meta(soup)
        if not subtitle_text:
            # Strategy 3: Structured data (last resort)
            subtitle_text = _find_subtitle_in_structured_data(soup)
        
        if subtitle_text:
            # Create a minimal structure for meta/structured data subtitles
            subtitle_info = {
                'text': subtitle_text,
                'element': None,
                'tag': None,
                'classes': [],
                'id': None,
                'style': None,
                'formatted_html': None
            }
    
    return {
        'title': title_info,
        'subtitle': subtitle_info
    }


def extract_headers_from_file(filepath: str) -> dict:
    """
    Extract headers from an HTML file.
    
    Args:
        filepath: Path to HTML file
        
    Returns:
        dict: Same format as extract_headers()
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return extract_headers(html_content)
    except Exception as e:
        return {'title': None, 'subtitle': None}


def main():
    """
    Main function for testing - uses site_preprocessing to scrape a page
    and then extracts headers.
    """
    import sys
    import site_preprocessing
    
    # Get URL from command line or use default
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "https://www.vogue.com/article/thin-little-scarf-fall-winter-trend"
        logger.info(f"No URL provided, using default: {url}")
        logger.info(f"Usage: python {sys.argv[0]} <url>")

    logger.info("=" * 80)
    logger.info("Step 1: Scraping webpage with ad-blocker...")
    logger.info("=" * 80)

    # Scrape the page
    html_content = site_preprocessing.scrape_page(url, wait_time=1)

    if not html_content:
        logger.error("Failed to scrape the page")
        sys.exit(1)

    logger.info("=" * 80)
    logger.info("Step 2: Extracting headers from HTML...")
    logger.info("=" * 80)

    # Extract headers
    headers = extract_headers(html_content)

    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)

    if headers['title']:
        logger.info("✓ Title found:")
        logger.info(f"  Text: {headers['title']['text']}")
        logger.info(f"  Tag: {headers['title']['tag']}")
        logger.info(f"  Classes: {headers['title']['classes']}")
        logger.info(f"  ID: {headers['title']['id']}")
        if headers['title']['formatted_html']:
            logger.info(f"  HTML: {headers['title']['formatted_html'][:200]}...")
    else:
        logger.info("✗ No title found")

    if headers['subtitle']:
        logger.info("✓ Subtitle found:")
        logger.info(f"  Text: {headers['subtitle']['text']}")
        logger.info(f"  Tag: {headers['subtitle']['tag']}")
        logger.info(f"  Classes: {headers['subtitle']['classes']}")
        logger.info(f"  ID: {headers['subtitle']['id']}")
        if headers['subtitle']['formatted_html']:
            logger.info(f"  HTML: {headers['subtitle']['formatted_html'][:200]}...")
    else:
        logger.info("✗ No subtitle found")
    
    return headers


if __name__ == "__main__":
    main()


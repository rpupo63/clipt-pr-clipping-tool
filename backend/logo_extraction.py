#!/usr/bin/env python3
"""
Extract specific page elements like logos from HTML documents
"""

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
import sys
import os
import json

# Import utilities
from logger import get_logger

logger = get_logger(__name__)


def extract_logo(html_content: str, root_domain: str, base_url: str = None) -> dict:
    """
    Extract the website's logo from HTML content.

    The logo can be found in multiple ways:
    1. <img> or <svg> tags with "logo" keyword (case-insensitive) in:
       - Element attributes: class, id, src, alt, title, name, aria-label, data-* attributes
       - Parent <a> tag attributes: class, id, title, aria-label, data-* attributes, etc.
       - Parent container attributes (up to 5 levels deep): class, id, role, data-*, aria-* attributes
       - Must be inside a link that points to the root domain
       - Must be an actual image file (svg, png, jpg, jpeg, gif, webp, etc.)

    2. JSON-LD structured data (schema.org)
       - Extracts publisher logo from NewsArticle, Article, Organization, etc.
       - Logo URL must be from the same domain or subdomain

    If multiple logos match, chooses the largest; if no size info, chooses the first.

    Args:
        html_content: HTML content as string
        root_domain: Root domain to match (e.g., "example.com" or "https://example.com")
        base_url: Base URL for converting relative paths to absolute URLs (e.g., "https://example.com/page")

    Returns:
        dict: Dictionary with keys:
            - 'element': The BeautifulSoup element (or None if not found)
            - 'src': The original image source (relative or absolute)
            - 'url': The absolute URL of the logo image (or None)
            - 'alt': The alt text (or None)
            - 'width': The width attribute (or None)
            - 'height': The height attribute (or None)
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Normalize root domain (remove protocol, trailing slash, www)
    root_domain_normalized = root_domain.lower().strip()
    root_domain_normalized = re.sub(r'^https?://', '', root_domain_normalized)
    root_domain_normalized = re.sub(r'^www\.', '', root_domain_normalized)
    root_domain_normalized = re.sub(r'/$', '', root_domain_normalized)
    
    # If base_url not provided, try to construct it from root_domain
    if not base_url:
        # Try to infer protocol from root_domain if it has one
        if root_domain.startswith('http://') or root_domain.startswith('https://'):
            parsed = urlparse(root_domain)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            # Default to https
            base_url = f"https://{root_domain_normalized}"
    
    # Image extensions to look for
    image_extensions = {'.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.tiff', '.tif'}
    
    # Find all images
    all_images = soup.find_all('img')
    
    # Also find SVG elements (they might be inline)
    all_svgs = soup.find_all('svg')
    
    # Combine images and SVGs for processing
    candidates = []
    
    # Helper function to check if "logo" appears in element or its parents
    def has_logo_keyword(element):
        """
        Check if "logo" appears anywhere in the element's attributes or parent elements.
        Checks: class, id, src, alt, title, name, aria-label, data-* attributes,
        and parent <a> tag, and parent containers (up to 5 levels deep).
        """
        # Check the element itself - all attributes
        for attr_name, attr_value in element.attrs.items():
            if attr_value:
                # Convert to string (handles lists like class)
                attr_str = ' '.join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                if re.search(r'logo', attr_str, re.IGNORECASE):
                    return True

        # Check parent <a> tag if it exists
        parent_link = element.find_parent('a')
        if parent_link:
            for attr_name, attr_value in parent_link.attrs.items():
                if attr_value:
                    attr_str = ' '.join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                    if re.search(r'logo', attr_str, re.IGNORECASE):
                        return True

        # Check parent containers (up to 4 levels) for "logo" in class, id, or data-* attributes
        # This allows checking: parent link, grandparent, great-grandparent, and one more level
        parent = element.parent
        levels = 0
        while parent and levels < 5:
            if parent.name:  # Make sure it's a tag, not NavigableString
                for attr_name, attr_value in parent.attrs.items():
                    # Focus on semantic attributes (class, id, data-*, role, aria-*)
                    if attr_name in ['class', 'id', 'role'] or attr_name.startswith('data-') or attr_name.startswith('aria-'):
                        if attr_value:
                            attr_str = ' '.join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                            if re.search(r'logo', attr_str, re.IGNORECASE):
                                return True
            parent = parent.parent
            levels += 1

        return False

    # Process <img> tags
    for img in all_images:
        # Get src and classes for later use
        src = img.get('src', '') or img.get('data-src', '') or img.get('data-lazy-src', '') or ''
        classes = img.get('class', [])

        # Check if "logo" appears anywhere in the element or its parents
        if not has_logo_keyword(img):
            continue

        # Check if it's an image file
        src_lower = src.lower()
        is_image = any(src_lower.endswith(ext) for ext in image_extensions) or \
                   any(ext in src_lower for ext in image_extensions) or \
                   src_lower.startswith('data:image/')

        if not is_image:
            continue

        # Check if image is inside a link that points to root domain
        parent_link = img.find_parent('a')
        if parent_link:
            href = parent_link.get('href', '')
            if href:
                # Normalize href - handle relative URLs
                if href.startswith('/'):
                    # Relative URL starting with / means same domain
                    href_domain = root_domain_normalized
                elif href.startswith('http://') or href.startswith('https://'):
                    # Absolute URL - parse domain
                    parsed_href = urlparse(href)
                    href_domain = parsed_href.netloc.lower()
                    href_domain = re.sub(r'^www\.', '', href_domain)
                else:
                    # Relative URL without leading / - also same domain
                    href_domain = root_domain_normalized

                # Check if it matches root domain or is root path
                if href_domain == root_domain_normalized or href == '/' or href == '':
                    # Convert relative src to absolute URL
                    absolute_url = None
                    if src:
                        if src.startswith('http://') or src.startswith('https://'):
                            absolute_url = src
                        elif src.startswith('//'):
                            # Protocol-relative URL
                            absolute_url = f"https:{src}"
                        elif src.startswith('/'):
                            # Absolute path on same domain
                            absolute_url = urljoin(base_url, src)
                        elif src.startswith('data:'):
                            # Data URI - keep as is
                            absolute_url = src
                        else:
                            # Relative path
                            absolute_url = urljoin(base_url, src)

                    candidates.append({
                        'element': img,
                        'type': 'img',
                        'src': src,
                        'url': absolute_url,
                        'alt': img.get('alt', ''),
                        'width': img.get('width'),
                        'height': img.get('height'),
                        'classes': classes
                    })
    
    # Process <svg> elements (they might be inside links)
    for svg in all_svgs:
        # Get classes for later use
        classes = svg.get('class', [])

        # Check if "logo" appears anywhere in the element or its parents
        if not has_logo_keyword(svg):
            continue

        # Check if SVG is inside a link that points to root domain
        parent_link = svg.find_parent('a')
        if parent_link:
            href = parent_link.get('href', '')
            if href:
                # Normalize href - handle relative URLs
                if href.startswith('/'):
                    href_domain = root_domain_normalized
                elif href.startswith('http://') or href.startswith('https://'):
                    parsed_href = urlparse(href)
                    href_domain = parsed_href.netloc.lower()
                    href_domain = re.sub(r'^www\.', '', href_domain)
                else:
                    href_domain = root_domain_normalized
                
                # Check if it matches root domain or is root path
                if href_domain == root_domain_normalized or href == '/' or href == '':
                    # For inline SVG, we can't provide a URL, but we can try to find a use element or image inside
                    svg_url = None
                    # Check if SVG contains an image or use element with href
                    use_elem = svg.find('use')
                    if use_elem and use_elem.get('href'):
                        href_attr = use_elem.get('href') or use_elem.get('xlink:href', '')
                        if href_attr:
                            if href_attr.startswith('http://') or href_attr.startswith('https://'):
                                svg_url = href_attr
                            else:
                                svg_url = urljoin(base_url, href_attr)
                    
                    candidates.append({
                        'element': svg,
                        'type': 'svg',
                        'src': None,  # SVG is inline
                        'url': svg_url,  # May be None for inline SVG
                        'alt': svg.get('aria-label', '') or svg.get('title', ''),
                        'width': svg.get('width'),
                        'height': svg.get('height'),
                        'classes': classes
                    })

    # Process JSON-LD structured data (e.g., schema.org)
    json_ld_scripts = soup.find_all('script', type='application/ld+json')
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)

            # Handle both single objects and arrays of objects
            data_items = data if isinstance(data, list) else [data]

            for item in data_items:
                if not isinstance(item, dict):
                    continue

                # Look for publisher logo in NewsArticle, Article, WebSite, Organization, etc.
                logo_data = None
                logo_name = None

                # Check if this is a schema.org type with publisher info
                if item.get('@type') in ['NewsArticle', 'Article', 'BlogPosting', 'WebPage', 'WebSite']:
                    publisher = item.get('publisher', {})
                    if isinstance(publisher, dict) and publisher.get('logo'):
                        logo_data = publisher.get('logo')
                        logo_name = publisher.get('name', '')

                # Check if this is an Organization with a logo
                elif item.get('@type') == 'Organization':
                    if item.get('logo'):
                        logo_data = item.get('logo')
                        logo_name = item.get('name', '')

                # If we found logo data, process it
                if logo_data:
                    logo_url = None
                    logo_width = None
                    logo_height = None

                    # logo_data can be a string URL or an ImageObject
                    if isinstance(logo_data, str):
                        logo_url = logo_data
                    elif isinstance(logo_data, dict):
                        logo_url = logo_data.get('url') or logo_data.get('@id')
                        logo_width = logo_data.get('width')
                        logo_height = logo_data.get('height')

                    # Validate the logo URL
                    if logo_url:
                        # Convert relative URLs to absolute
                        if not logo_url.startswith('http://') and not logo_url.startswith('https://'):
                            logo_url = urljoin(base_url, logo_url)

                        # Check if the logo URL is from the same domain or a trusted CDN
                        # For structured data, we're more lenient - we trust schema.org publisher logos
                        parsed_logo = urlparse(logo_url)
                        logo_domain = parsed_logo.netloc.lower()
                        logo_domain = re.sub(r'^www\.', '', logo_domain)

                        # Accept if it's the same domain OR if it's from a CDN/media subdomain
                        # (e.g., media.fashionunited.com for fashionunited.com)
                        is_valid = False
                        if logo_domain == root_domain_normalized:
                            is_valid = True
                        elif root_domain_normalized in logo_domain:
                            # Check if it's a subdomain (e.g., media.example.com for example.com)
                            is_valid = True

                        if is_valid:
                            candidates.append({
                                'element': script,  # Reference to the script tag
                                'type': 'json-ld',
                                'src': logo_url,
                                'url': logo_url,
                                'alt': logo_name or 'Publisher Logo',
                                'width': logo_width,
                                'height': logo_height,
                                'classes': []
                            })
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            # Skip invalid JSON-LD
            continue

    # If no candidates found, return None
    if not candidates:
        return {
            'element': None,
            'src': None,
            'url': None,
            'alt': None,
            'width': None,
            'height': None
        }
    
    # Sort candidates by size (largest first)
    def get_size(candidate):
        """Get the size of an image candidate for sorting"""
        width = candidate.get('width')
        height = candidate.get('height')
        
        # Try to parse width and height
        try:
            if width:
                width = int(re.sub(r'[^\d]', '', str(width)))
            else:
                width = 0
            if height:
                height = int(re.sub(r'[^\d]', '', str(height)))
            else:
                height = 0
            
            # Return area (width * height) for sorting
            return width * height
        except (ValueError, TypeError):
            return 0
    
    # Sort by size (largest first)
    candidates.sort(key=get_size, reverse=True)
    
    # Get the largest (first after sorting)
    best_candidate = candidates[0]
    
    return {
        'element': best_candidate['element'],
        'src': best_candidate['src'],
        'url': best_candidate['url'],
        'alt': best_candidate['alt'],
        'width': best_candidate['width'],
        'height': best_candidate['height']
    }


def get_root_domain(url: str) -> str:
    """
    Extract the root domain from a URL using urllib.parse.
    
    Args:
        url: Full URL (e.g., "https://www.example.com/path/to/page")
    
    Returns:
        str: Root domain without protocol, www, or trailing slash (e.g., "example.com")
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # Remove www. prefix if present
    domain = re.sub(r'^www\.', '', domain)
    
    # Remove port if present (e.g., example.com:8080 -> example.com)
    if ':' in domain:
        domain = domain.split(':')[0]
    
    return domain


def extract_logo_from_file(filepath: str, root_domain: str, base_url: str = None) -> dict:
    """
    Extract logo from an HTML file.
    
    Args:
        filepath: Path to HTML file
        root_domain: Root domain to match
        base_url: Base URL for converting relative paths to absolute URLs
    
    Returns:
        dict: Same format as extract_logo()
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return extract_logo(f.read(), root_domain, base_url)


def main():
    """
    Main function that:
    1. Calls site_preprocessing.scrape_page() to scrape a webpage
    2. Extracts the root domain from the URL
    3. Calls extract_logo() to find the logo
    4. Displays the results
    """
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

    # Save HTML to file for reference
    html_file = "scraped_page.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logger.info(f"✓ HTML saved to: {html_file}")

    logger.info("=" * 80)
    logger.info("Step 2: Extracting root domain from URL...")
    logger.info("=" * 80)

    # Extract root domain from URL
    root_domain = get_root_domain(url)
    logger.info(f"✓ Root domain: {root_domain}")

    logger.info("=" * 80)
    logger.info("Step 3: Extracting logo from HTML...")
    logger.info("=" * 80)

    # Extract logo (pass base_url to convert relative paths to absolute URLs)
    logo_result = extract_logo(html_content, root_domain, base_url=url)

    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)

    if logo_result['element']:
        logger.info("✓ Logo found!")
        logger.info(f"  Logo URL (absolute): {logo_result['url']}")
        logger.info(f"  Original source: {logo_result['src'] or '(inline SVG)'}")
        logger.info(f"  Alt text: {logo_result['alt'] or '(none)'}")
        logger.info(f"  Dimensions: {logo_result['width'] or 'N/A'} x {logo_result['height'] or 'N/A'}")
        logger.info("  Element HTML:")
        logger.info("  " + str(logo_result['element']).replace('\n', '\n  '))
    else:
        logger.info("✗ No logo found matching the criteria")
        logger.info("  Criteria checked:")
        logger.info("  - Has 'logo' in class name, id, or image path")
        logger.info("  - Is inside a link pointing to root domain")
        logger.info("  - Is an image file (svg, png, jpg, etc.)")
    
    return logo_result


if __name__ == "__main__":
    main()


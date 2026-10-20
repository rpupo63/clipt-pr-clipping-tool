#!/usr/bin/env python3
"""
Image utility functions for downloading, parsing, and extracting image information.
Handles srcset parsing, image downloading, and dimension extraction.
"""

from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
import requests
import re
from io import BytesIO

# Import utilities
from constants import ImageConfig, NetworkConfig
from logger import get_logger
from network_utils import download_with_size_limit

logger = get_logger(__name__)

# Try to import PIL for getting actual image dimensions
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL not available - image dimension detection will be limited")


def _get_dimensions_from_headers(image_bytes: bytes) -> Tuple[Optional[int], Optional[int]]:
    """
    Fallback method to get image dimensions from image file headers.
    Used when PIL is not available.

    Supports: JPEG, PNG, GIF, WebP (basic detection)

    Args:
        image_bytes: Raw image data

    Returns:
        tuple: (width, height) or (None, None) if unable to determine
    """
    if not image_bytes or len(image_bytes) < 24:
        return None, None

    # Check PNG signature
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        # PNG: width and height are at bytes 16-23
        if len(image_bytes) >= 24:
            width = int.from_bytes(image_bytes[16:20], 'big')
            height = int.from_bytes(image_bytes[20:24], 'big')
            return width, height

    # Check JPEG signature
    elif image_bytes[:2] == b'\xff\xd8':
        # JPEG: more complex, requires parsing segments
        # Simplified approach - look for SOF marker
        try:
            i = 2
            while i < len(image_bytes) - 10:
                if image_bytes[i] == 0xff:
                    marker = image_bytes[i + 1]
                    # SOF markers: 0xC0-0xC3, 0xC5-0xC7, 0xC9-0xCB, 0xCD-0xCF
                    if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
                                  0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                        # Height at i+5, width at i+7
                        height = int.from_bytes(image_bytes[i+5:i+7], 'big')
                        width = int.from_bytes(image_bytes[i+7:i+9], 'big')
                        return width, height
                    # Skip to next segment
                    length = int.from_bytes(image_bytes[i+2:i+4], 'big')
                    i += 2 + length
                else:
                    i += 1
        except Exception:
            pass

    # Check GIF signature
    elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
        # GIF: width at bytes 6-7, height at 8-9 (little-endian)
        if len(image_bytes) >= 10:
            width = int.from_bytes(image_bytes[6:8], 'little')
            height = int.from_bytes(image_bytes[8:10], 'little')
            return width, height

    # Check WebP signature
    elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        # WebP: more complex, requires parsing chunks
        # Simplified for VP8/VP8L
        if len(image_bytes) >= 30:
            if image_bytes[12:16] == b'VP8 ':
                # Lossy WebP
                width = int.from_bytes(image_bytes[26:28], 'little') & 0x3fff
                height = int.from_bytes(image_bytes[28:30], 'little') & 0x3fff
                return width, height
            elif image_bytes[12:16] == b'VP8L':
                # Lossless WebP
                bits = int.from_bytes(image_bytes[21:25], 'little')
                width = (bits & 0x3fff) + 1
                height = ((bits >> 14) & 0x3fff) + 1
                return width, height

    return None, None


def parse_srcset(srcset_str: str) -> List[Tuple[str, Optional[float]]]:
    """
    Parse a srcset string and return list of (url, descriptor_value) tuples.
    
    Handles both width descriptors (e.g., "image.jpg 1920w") and 
    density descriptors (e.g., "image.jpg 2x").
    
    Args:
        srcset_str: srcset attribute value
        
    Returns:
        list: List of (url, descriptor_value) tuples, sorted by descriptor (highest first)
              descriptor_value is width in pixels for 'w' descriptors, or density for 'x' descriptors
    """
    if not srcset_str:
        return []

    # SECURITY: Limit srcset length to prevent DoS
    if len(srcset_str) > NetworkConfig.MAX_SRCSET_LENGTH:
        logger.warning(f"Srcset too long: {len(srcset_str)} chars, truncating")
        srcset_str = srcset_str[:NetworkConfig.MAX_SRCSET_LENGTH]

    sources = []
    # Split by comma, but be careful of commas in URLs
    parts = []
    current_part = ''
    in_parens = False

    for i, char in enumerate(srcset_str):
        # Safety check: prevent infinite processing
        if i > NetworkConfig.MAX_SRCSET_LENGTH:
            logger.warning("Srcset parsing exceeded max length")
            break
        if char == '(':
            in_parens = True
            current_part += char
        elif char == ')':
            in_parens = False
            current_part += char
        elif char == ',' and not in_parens:
            if current_part.strip():
                parts.append(current_part.strip())
            current_part = ''
        else:
            current_part += char
    
    if current_part.strip():
        parts.append(current_part.strip())
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Split into URL and descriptor
        # Descriptor can be at the end: "url 1920w" or "url 2x"
        # Use regex to find the descriptor
        # Match descriptor: optional number, optional decimal, followed by 'w' or 'x'
        descriptor_match = re.search(r'\s+(\d+(?:\.\d+)?)([wx])$', part)
        
        if descriptor_match:
            descriptor_value = float(descriptor_match.group(1))
            descriptor_type = descriptor_match.group(2)
            url = part[:descriptor_match.start()].strip()
            
            # For width descriptors, store as-is
            # For density descriptors, we'll prioritize higher density
            if descriptor_type == 'w':
                sources.append((url, descriptor_value))
            else:  # 'x' descriptor
                sources.append((url, descriptor_value))
        else:
            # No descriptor, treat as 1x density
            sources.append((part.strip(), 1.0))
    
    # Sort by descriptor value (highest first)
    sources.sort(key=lambda x: x[1] if x[1] is not None else 0, reverse=True)
    return sources


def get_best_image_from_srcset(srcset_str: str, base_url: Optional[str] = None) -> Optional[str]:
    """
    Extract the highest quality image URL from a srcset string.
    
    Args:
        srcset_str: srcset attribute value
        base_url: Base URL for converting relative paths to absolute URLs
        
    Returns:
        str: Best quality image URL (absolute if base_url provided) or None
    """
    if not srcset_str:
        return None
    
    sources = parse_srcset(srcset_str)
    if not sources:
        return None
    
    # Get the first (highest quality) source
    best_url = sources[0][0]
    
    # Convert to absolute URL if base_url provided
    if best_url and base_url:
        return urljoin(base_url, best_url)
    elif best_url and best_url.startswith('http'):
        return best_url
    
    return best_url


def download_image(url: str) -> Tuple[Optional[bytes], Optional[int], Optional[int]]:
    """
    Download image and get its dimensions (with memory safety).

    This is a shared utility function to avoid redundant downloads.
    Can be used by other modules to download images and get dimensions in one call.

    SECURITY: Uses size-limited download to prevent memory exhaustion.

    Args:
        url: Image URL

    Returns:
        tuple: (image_bytes, width, height) or (None, None, None) if unable to fetch
               image_bytes can be used to avoid re-downloading later
    """
    if not url:
        return None, None, None

    try:
        # SECURITY: Download image with size limit to prevent memory exhaustion
        image_bytes = download_with_size_limit(
            url,
            max_size=ImageConfig.MAX_SIZE,
            timeout=ImageConfig.TIMEOUT
        )

        width, height = None, None

        # Get dimensions using PIL if available
        if PIL_AVAILABLE:
            try:
                img_data = BytesIO(image_bytes)
                with Image.open(img_data) as img:
                    width, height = img.size  # Returns (width, height)
                    logger.debug(f"Downloaded image: {url} ({width}x{height})")
            except Exception as e:
                logger.warning(f"Could not get image dimensions for {url}: {e}")
        else:
            # PIL not available - try to extract dimensions from bytes
            width, height = _get_dimensions_from_headers(image_bytes)
            logger.debug(f"Downloaded image: {url} (dimensions via headers)")

        return image_bytes, width, height

    except ValueError as e:
        # Size limit exceeded
        logger.error(f"Image too large: {url} - {e}")
        return None, None, None
    except Exception as e:
        # If anything else fails, return None
        logger.warning(f"Failed to download image {url}: {e}")
        return None, None, None


def get_actual_image_dimensions(url: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Fetch actual image dimensions from URL using PIL.
    
    This function uses the shared download_image utility to avoid code duplication.
    
    Args:
        url: Image URL
        
    Returns:
        tuple: (width, height) or (None, None) if unable to fetch
    """
    _, width, height = download_image(url)
    return width, height


def extract_image_info(img_element, base_url: Optional[str] = None, fetch_dimensions: bool = True, fetch_content: bool = False) -> Dict:
    """
    Extract information from an image element.
    
    Args:
        img_element: BeautifulSoup image element (img, picture, or figure)
        base_url: Base URL for converting relative paths to absolute URLs
        fetch_dimensions: If True, fetch actual image dimensions from URL (default: True)
        fetch_content: If True, download and store image content to avoid re-downloading (default: False)
        
    Returns:
        dict: Dictionary with image information:
            - 'element': BeautifulSoup element
            - 'src': Image source URL (relative or absolute)
            - 'url': Absolute URL (or None)
            - 'alt': Alt text (or None)
            - 'width': Width attribute or actual width (or None)
            - 'height': Height attribute or actual height (or None)
            - 'actual_width': Actual image width from file (or None)
            - 'actual_height': Actual image height from file (or None)
            - 'type': Type of element ('img', 'picture', 'figure')
            - 'content': Image bytes (only if fetch_content=True and download successful)
    """
    if img_element is None:
        return {
            'element': None,
            'src': None,
            'url': None,
            'alt': None,
            'width': None,
            'height': None,
            'actual_width': None,
            'actual_height': None,
            'type': None
        }
    
    # Find the actual img tag if element is picture or figure
    actual_img = img_element
    is_picture = False
    if img_element.name == 'picture':
        is_picture = True
        actual_img = img_element.find('img')
        if actual_img is None:
            return {
                'element': img_element,
                'src': None,
                'url': None,
                'alt': None,
                'width': None,
                'height': None,
                'actual_width': None,
                'actual_height': None,
                'type': img_element.name
            }
    elif img_element.name != 'img':
        actual_img = img_element.find('img')
        if actual_img is None:
            return {
                'element': img_element,
                'src': None,
                'url': None,
                'alt': None,
                'width': None,
                'height': None,
                'actual_width': None,
                'actual_height': None,
                'type': img_element.name
            }
    
    # Priority order for getting highest quality image:
    # 1. picture source srcset (responsive images in picture element - get highest resolution)
    # 2. img srcset (responsive images - get highest resolution)
    # 3. data-srcset (lazy-loaded responsive images)
    # 4. data-src (lazy-loaded single image)
    # 5. data-lazy-src (alternative lazy-load attribute)
    # 6. data-original (original quality lazy-load)
    # 7. src (fallback)
    
    url = None
    src = None
    
    # If it's a picture element, check source elements first (they often have higher quality)
    if is_picture:
        source_elements = img_element.find_all('source')
        all_srcsets = []
        for source in source_elements:
            source_srcset = source.get('srcset') or source.get('data-srcset')
            if source_srcset:
                all_srcsets.append(source_srcset)
        
        # Parse all srcsets and find the highest quality image
        best_url_from_sources = None
        best_descriptor = 0
        for srcset_str in all_srcsets:
            sources = parse_srcset(srcset_str)
            if sources and sources[0][1] and sources[0][1] > best_descriptor:
                best_descriptor = sources[0][1]
                candidate_url = sources[0][0]
                if candidate_url and base_url:
                    best_url_from_sources = urljoin(base_url, candidate_url)
                elif candidate_url and candidate_url.startswith('http'):
                    best_url_from_sources = candidate_url
                else:
                    best_url_from_sources = candidate_url
        
        if best_url_from_sources:
            url = best_url_from_sources
            src = best_url_from_sources
    
    # Check for srcset on img element (if not already found from picture sources)
    if not url:
        srcset = actual_img.get('srcset') or actual_img.get('data-srcset')
        if srcset:
            best_url = get_best_image_from_srcset(srcset, base_url)
            if best_url:
                url = best_url
                src = best_url  # Store the best URL as src
    
    # If no srcset, try lazy-load attributes
    if not url:
        src = (actual_img.get('data-src') or 
               actual_img.get('data-lazy-src') or
               actual_img.get('data-original') or
               actual_img.get('src') or
               '')
        
        # Get absolute URL if base_url provided
        if src and base_url:
            url = urljoin(base_url, src)
        elif src and src.startswith('http'):
            url = src
    
    # Get HTML attributes
    alt = actual_img.get('alt')
    width_attr = actual_img.get('width')
    height_attr = actual_img.get('height')
    
    # Try to convert width/height attributes to integers
    width = None
    height = None
    if width_attr:
        try:
            width = int(width_attr)
        except (ValueError, TypeError):
            pass
    if height_attr:
        try:
            height = int(height_attr)
        except (ValueError, TypeError):
            pass
    
    # Fetch actual dimensions and optionally content if requested and URL is available
    actual_width = None
    actual_height = None
    image_content = None
    if (fetch_dimensions or fetch_content) and url:
        image_content, actual_width, actual_height = download_image(url)
        # Use actual dimensions if HTML attributes are missing
        if width is None and actual_width is not None:
            width = actual_width
        if height is None and actual_height is not None:
            height = actual_height
    
    result = {
        'element': img_element,
        'src': src,
        'url': url,
        'alt': alt,
        'width': width,
        'height': height,
        'actual_width': actual_width,
        'actual_height': actual_height,
        'type': img_element.name
    }
    
    # Optionally include image content to avoid re-downloading
    if fetch_content and image_content is not None:
        result['content'] = image_content
    
    return result




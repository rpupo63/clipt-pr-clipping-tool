#!/usr/bin/env python3
"""
Main function to process a URL and generate output in various formats.
Combines all extraction modules to create a formatted document.
"""

import sys
import os
import html
import tempfile
import uuid
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs

# Import all the extraction modules
import site_preprocessing
import content_extraction
import header_extraction
import positional_extraction
import logo_extraction
import output_generation
import find_first_and_last_sentences

# Import utilities
from url_utils import normalize_image_url
from constants import FileConfig, ContentConfig
from logger import get_logger

logger = get_logger(__name__)


# Note: normalize_image_url removed - now using normalize_image_url from url_utils


def process_url_to_file(url: str, filetype: str = 'html', output_file: str = None, keywords: list = None, include_first_paragraph: bool = False, use_ai_extraction: bool = True) -> str:
    """
    Process a URL and generate output in the specified format.

    This function:
    1. Scrapes the webpage with ad-blocking
    2. Extracts logo, headers (title/subtitle), and main content
    3. (Optional) Uses AI to identify first/last contentful sentences for precise extraction
    4. Validates subtitle position
    5. Finds and inserts images around paragraphs
    6. Generates formatted HTML and converts to requested format

    Args:
        url: URL to process
        filetype: Output format ('html', 'docx', 'pdf', 'md', 'markdown')
        output_file: Optional output file path (defaults to auto-generated name)
        keywords: Optional list of keywords to filter paragraphs. Only paragraphs
                 containing at least one keyword will be included.
        include_first_paragraph: If True, always include the first paragraph even if it
                                doesn't contain any keywords. Only applies when keywords are provided.
        use_ai_extraction: If True (default), uses Firecrawl + OpenAI to identify content boundaries.
                          Requires FIRECRAWL_API_KEY and OPENAI_API_KEY in .env file.
                          If False or if extraction fails, falls back to heuristic extraction.

    Returns:
        str: Path to the generated output file
    """
    logger.info("=" * 80)
    logger.info("Step 1: Scraping webpage with ad-blocker...")
    logger.info("=" * 80)

    # Step 1: Scrape the page
    html_content = site_preprocessing.scrape_page(url, wait_time=1)

    if not html_content:
        raise Exception("Failed to scrape the page")

    # SECURITY FIX: Use temp directory for file writes
    temp_dir = Path(tempfile.gettempdir()) / FileConfig.TEMP_DIR_NAME
    temp_dir.mkdir(exist_ok=True, parents=True)

    # Save original HTML for reference with unique filename
    original_html_file = temp_dir / f"scraped_page_{uuid.uuid4().hex[:8]}.html"
    with open(original_html_file, 'w', encoding=FileConfig.DEFAULT_ENCODING) as f:
        f.write(html_content)
    logger.info(f"✓ Original HTML saved to: {original_html_file}")

    logger.info("=" * 80)
    logger.info("Step 2: Extracting logo...")
    logger.info("=" * 80)

    # Step 2: Extract logo
    root_domain = logo_extraction.get_root_domain(url)
    logo_result = logo_extraction.extract_logo(html_content, root_domain, base_url=url)

    if logo_result['element']:
        logger.info(f"✓ Logo found: {logo_result['url'] or logo_result['src']}")
    else:
        logger.info("⚠ No logo found")

    logger.info("=" * 80)
    logger.info("Step 3: Extracting headers (title and subtitle)...")
    logger.info("=" * 80)

    # Step 3: Extract headers
    headers = header_extraction.extract_headers(html_content)

    if headers['title']:
        logger.info(f"✓ Title found: {headers['title']['text'][:80]}...")
    else:
        logger.info("⚠ No title found")

    if headers['subtitle']:
        logger.info(f"✓ Subtitle found: {headers['subtitle']['text'][:80]}...")
    else:
        logger.info("⚠ No subtitle found")

    logger.info("=" * 80)
    logger.info("Step 3.5: Finding image below title...")
    logger.info("=" * 80)

    # Step 3.5: Find image below title
    title_image = positional_extraction.find_image_below_title(
        html_content,
        headers,
        base_url=url,
        max_distance=5
    )

    if title_image:
        img_url = title_image if isinstance(title_image, str) else title_image.get('url')
        if img_url:
            logger.info(f"✓ Title image found: {img_url}")
    else:
        logger.info("⚠ No image found below title")

    logger.info("=" * 80)
    logger.info("Step 3.75: Finding first and last contentful sentences...")
    logger.info("=" * 80)

    # Step 3.75: Extract first and last sentences using Firecrawl + OpenAI
    # This helps identify the precise content boundaries
    first_sentence = None
    last_sentence = None

    if use_ai_extraction:
        sentence_result = find_first_and_last_sentences.find_first_and_last_sentences_from_url(
            url,
            use_firecrawl=True
        )

        if sentence_result['success']:
            first_sentence = sentence_result['first_sentence']
            last_sentence = sentence_result['last_sentence']
            logger.info("✓ Successfully extracted content boundaries")
        else:
            logger.info(f"⚠ Could not extract sentences: {sentence_result['error']}")
            logger.info("  Will use heuristic content extraction instead")
    else:
        logger.info("  AI extraction disabled - using heuristic content extraction")

    logger.info("=" * 80)
    logger.info("Step 4: Extracting main content...")
    logger.info("=" * 80)

    # Step 4: Extract main content
    if keywords:
        logger.info(f"  Filtering paragraphs by keywords: {', '.join(keywords)}")
        if include_first_paragraph:
            logger.info("  Always including first paragraph (even if it doesn't match keywords)")

    if first_sentence and last_sentence:
        logger.info("  Using AI-identified content boundaries for precise extraction")

    extracted_content_html = content_extraction.extract_main_content(
        html_content,
        first_sentence=first_sentence,
        last_sentence=last_sentence,
        keywords=keywords,
        include_first_paragraph=include_first_paragraph
    )
    if keywords:
        # Count paragraphs after filtering
        extracted_soup = BeautifulSoup(extracted_content_html, 'html.parser')
        para_count = len(extracted_soup.find_all('p'))
        logger.info(f"✓ Main content extracted ({para_count} paragraphs after keyword filtering)")
    else:
        logger.info("✓ Main content extracted")

    logger.info("=" * 80)
    logger.info("Step 5: Validating subtitle position...")
    logger.info("=" * 80)
    
    # Step 5: Validate subtitle position
    subtitle_validation = positional_extraction.validate_subtitle_position(
        html_content,
        headers,
        extracted_content_html
    )
    
    include_subtitle = subtitle_validation['is_valid']
    if include_subtitle:
        logger.info("✓ Subtitle is correctly positioned - will be included")
    else:
        logger.info(f"⚠ Subtitle validation failed: {subtitle_validation['reason']}")
        logger.info("  Subtitle will not be included")

    logger.info("=" * 80)
    logger.info("Step 6: Finding images around paragraphs...")
    logger.info("=" * 80)
    
    # Step 6: Find images around paragraphs
    extracted_soup = BeautifulSoup(extracted_content_html, 'html.parser')
    paragraphs = extracted_soup.find_all('p')
    
    # Track images to avoid duplicates using normalized URLs
    # Use both original and normalized URLs for tracking
    seen_image_urls = set()  # Original URLs (for display/logging)
    seen_normalized_urls = set()  # Normalized URLs (for duplicate detection)
    
    # Start with title image if it exists
    # title_image is now just a URL string (or None)
    if title_image:
        img_url = title_image if isinstance(title_image, str) else title_image.get('url')
        if img_url:
            normalized_url = normalize_image_url(img_url)
            seen_image_urls.add(img_url)
            seen_normalized_urls.add(normalized_url)
    
    paragraph_image_map = {}  # Maps paragraph index to images above/below
    
    for i, para in enumerate(paragraphs):
        image_result = positional_extraction.find_images_around_paragraph_from_extracted_content(
            extracted_content_html,
            i,
            html_content,
            base_url=url,
            max_distance=5
        )
        
        if image_result['paragraph_matched']:
            images_found = []
            
            # Check image above (now just a URL string)
            if image_result['image_above']:
                img_url = image_result['image_above']
                normalized_url = normalize_image_url(img_url)
                # Check against normalized URLs to catch duplicates with different query params
                if normalized_url not in seen_normalized_urls:
                    seen_image_urls.add(img_url)
                    seen_normalized_urls.add(normalized_url)
                    images_found.append(('above', img_url))
            
            # Check image below (now just a URL string)
            if image_result['image_below']:
                img_url = image_result['image_below']
                normalized_url = normalize_image_url(img_url)
                # Check against normalized URLs to catch duplicates with different query params
                if normalized_url not in seen_normalized_urls:
                    seen_image_urls.add(img_url)
                    seen_normalized_urls.add(normalized_url)
                    images_found.append(('below', img_url))
            
            if images_found:
                paragraph_image_map[i] = images_found
    
    logger.info(f"✓ Found {len(seen_normalized_urls)} unique images (including title image)")

    logger.info("=" * 80)
    logger.info("Step 7: Building final HTML document...")
    logger.info("=" * 80)
    
    # Step 7: Build final HTML document
    final_html = build_final_html(
        logo_result,
        headers,
        include_subtitle,
        extracted_content_html,
        paragraph_image_map,
        title_image,
        seen_image_urls
    )
    
    # SECURITY FIX: Save intermediate HTML file to temp directory with unique filename
    intermediate_html_file = temp_dir / f"final_content_{uuid.uuid4().hex[:8]}.html"
    with open(intermediate_html_file, 'w', encoding=FileConfig.DEFAULT_ENCODING) as f:
        f.write(final_html)
    logger.info(f"✓ Final HTML saved to: {intermediate_html_file}")

    logger.info("=" * 80)
    logger.info(f"Step 8: Converting to {filetype.upper()} format...")
    logger.info("=" * 80)
    
    # Step 8: Convert to requested format
    if filetype.lower() == 'html':
        # For HTML, just use the intermediate file
        if output_file:
            import shutil
            shutil.copy(intermediate_html_file, output_file)
            return output_file
        return intermediate_html_file
    else:
        # Use output_generation to convert (returns content, not file path)
        converted_content = output_generation.convert_html(final_html, filetype)
        
        # Determine output filename
        if output_file is None:
            from urllib.parse import urlparse
            from pathlib import Path
            parsed_url = urlparse(url)
            base_name = Path(parsed_url.path).stem or "output"
            if not base_name or base_name == "/":
                base_name = "output"
            
            # Get appropriate extension
            ext_map = {
                'docx': '.docx',
                'doc': '.docx',
                'pdf': '.pdf',
                'md': '.md',
                'markdown': '.md'
            }
            ext = ext_map.get(filetype.lower(), '.txt')
            output_file = f"{base_name}{ext}"
        
        # Save the content to file
        if filetype.lower() in ['docx', 'doc', 'pdf']:
            # Binary format
            with open(output_file, 'wb') as f:
                f.write(converted_content)
        else:
            # Text format (markdown)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(converted_content)

        logger.info(f"✓ Output saved to: {output_file}")
        return output_file


def build_final_html(logo_result: dict, headers: dict, include_subtitle: bool,
                     extracted_content_html: str, paragraph_image_map: dict,
                     title_image: dict = None, seen_image_urls: set = None) -> str:
    """
    Build the final HTML document with logo, headers, content, and images.
    
    Args:
        logo_result: Logo extraction result from logo_extraction.extract_logo()
        headers: Headers dict from header_extraction.extract_headers()
        include_subtitle: Whether to include subtitle (based on validation)
        extracted_content_html: HTML content from content_extraction.extract_main_content()
        paragraph_image_map: Dict mapping paragraph indices to images above/below
        title_image: Optional str with image URL below title (from positional_extraction.find_image_below_title)
        seen_image_urls: Set of image URLs already seen to prevent duplicates
        
    Returns:
        str: Complete HTML document
    """
    # Initialize seen_image_urls if not provided
    if seen_image_urls is None:
        seen_image_urls = set()
    
    # Track images added to HTML to prevent duplicates using normalized URLs
    added_image_urls = set()  # Original URLs (for tracking)
    added_normalized_urls = set()  # Normalized URLs (for duplicate detection)
    
    # Parse extracted content
    content_soup = BeautifulSoup(extracted_content_html, 'html.parser')
    
    # Get title from extracted content or headers
    title_text = ""
    if content_soup.find('title'):
        title_text = content_soup.find('title').get_text(strip=True)
    elif headers.get('title') and headers['title'].get('text'):
        title_text = headers['title']['text']
    
    # Start building HTML
    html_parts = ['<!DOCTYPE html>']
    html_parts.append('<html>')
    html_parts.append('<head>')
    html_parts.append('    <meta charset="utf-8">')
    html_parts.append(f'    <title>{title_text}</title>')
    html_parts.append('    <style>')
    html_parts.append('        body {')
    html_parts.append('            font-family: Georgia, serif;')
    html_parts.append('            max-width: 800px;')
    html_parts.append('            margin: 0 auto;')
    html_parts.append('            padding: 20px;')
    html_parts.append('            line-height: 1.6;')
    html_parts.append('        }')
    html_parts.append('        .logo-container {')
    html_parts.append('            text-align: center;')
    html_parts.append('            margin: 20px 0 40px 0;')
    html_parts.append('        }')
    html_parts.append('        .logo-container img {')
    html_parts.append('            width: 33.333%;')
    html_parts.append('            max-width: 100%;')
    html_parts.append('            height: auto;')
    html_parts.append('            display: block;')
    html_parts.append('            margin: 0 auto;')
    html_parts.append('        }')
    html_parts.append('        h1 {')
    html_parts.append('            text-align: center;')
    html_parts.append('            margin: 30px 0 20px 0;')
    html_parts.append('        }')
    html_parts.append('        .subtitle {')
    html_parts.append('            text-align: center;')
    html_parts.append('            font-style: italic;')
    html_parts.append('            color: #666;')
    html_parts.append('            margin: 0 0 30px 0;')
    html_parts.append('            font-size: 1.1em;')
    html_parts.append('        }')
    html_parts.append('        .content-image {')
    html_parts.append('            width: 33.333%;')
    html_parts.append('            max-width: 100%;')
    html_parts.append('            height: auto;')
    html_parts.append('            margin: 20px auto;')
    html_parts.append('            display: block;')
    html_parts.append('        }')
    html_parts.append('        p {')
    html_parts.append('            margin: 15px 0;')
    html_parts.append('        }')
    html_parts.append('    </style>')
    html_parts.append('</head>')
    html_parts.append('<body>')
    
    # Add logo (centered, fixed width)
    if logo_result.get('element'):
        html_parts.append('    <div class="logo-container">')
        logo_url = logo_result.get('url') or logo_result.get('src')
        if logo_url:
            # SECURITY: Properly escape URL and alt text for HTML
            logo_url_escaped = html.escape(logo_url, quote=True)
            img_alt = logo_result.get('alt', '') or 'Logo'
            img_alt_escaped = html.escape(img_alt, quote=True)
            html_parts.append(f'        <img src="{logo_url_escaped}" alt="{img_alt_escaped}" />')
        elif logo_result.get('element') and hasattr(logo_result['element'], 'name') and logo_result['element'].name == 'svg':
            # Handle inline SVG
            svg_html = str(logo_result['element'])
            html_parts.append(f'        {svg_html}')
        html_parts.append('    </div>')
    
    # Add title with preserved formatting
    if headers.get('title') and headers['title'].get('text'):
        title_info = headers['title']
        # Use formatted_html if available (preserves all formatting)
        if title_info.get('formatted_html'):
            # Extract just the inner HTML content, keeping the tag structure
            formatted_title = title_info['formatted_html']
            # If it's a full element, we can use it directly (but need to handle potential wrapper)
            html_parts.append(f'    {formatted_title}')
        else:
            # Fallback: reconstruct with basic formatting if available
            tag = title_info.get('tag') or 'h1'
            classes = title_info.get('classes', [])
            style = title_info.get('style', '')
            title_id = title_info.get('id', '')
            
            # Build attributes with proper escaping
            attrs = []
            if classes:
                class_str = ' '.join(classes)
                class_str_escaped = html.escape(class_str, quote=True)
                attrs.append(f'class="{class_str_escaped}"')
            if style:
                style_escaped = html.escape(style, quote=True)
                attrs.append(f'style="{style_escaped}"')
            if title_id:
                id_escaped = html.escape(title_id, quote=True)
                attrs.append(f'id="{id_escaped}"')

            attr_str = ' ' + ' '.join(attrs) if attrs else ''
            # SECURITY: Properly escape title text for HTML
            title_text_escaped = html.escape(title_info['text'], quote=False)
            html_parts.append(f'    <{tag}{attr_str}>{title_text_escaped}</{tag}>')
    
    # Add title image if found (after title, before subtitle)
    # Only add if not already seen (to prevent duplicates)
    # title_image is now just a URL string (or None)
    if title_image:
        img_url = title_image if isinstance(title_image, str) else title_image.get('url')
        if img_url:
            normalized_url = normalize_image_url(img_url)
            # Check against normalized URLs to catch duplicates with different query params
            if normalized_url not in added_normalized_urls:
                added_image_urls.add(img_url)
                added_normalized_urls.add(normalized_url)
                # SECURITY: Properly escape URL for HTML
                img_url_escaped = html.escape(img_url, quote=True)
                # Use consistent image sizing (width set via CSS, height auto for aspect ratio)
                # Alt text will be empty - output_generation will handle deduplication and processing
                html_parts.append(f'    <img src="{img_url_escaped}" alt="" class="content-image" />')
    
    # Add subtitle if valid, with preserved formatting
    if include_subtitle and headers.get('subtitle') and headers['subtitle'].get('text'):
        subtitle_info = headers['subtitle']
        # Use formatted_html if available (preserves all formatting)
        if subtitle_info.get('formatted_html'):
            formatted_subtitle = subtitle_info['formatted_html']
            html_parts.append(f'    {formatted_subtitle}')
        else:
            # Fallback: reconstruct with formatting
            tag = subtitle_info.get('tag') or 'div'
            classes = subtitle_info.get('classes', [])
            style = subtitle_info.get('style', '')
            subtitle_id = subtitle_info.get('id', '')
            
            # Add subtitle class if not present
            if 'subtitle' not in ' '.join(classes).lower():
                classes.append('subtitle')
            
            # Build attributes with proper escaping
            attrs = []
            if classes:
                class_str = ' '.join(classes)
                class_str_escaped = html.escape(class_str, quote=True)
                attrs.append(f'class="{class_str_escaped}"')
            if style:
                style_escaped = html.escape(style, quote=True)
                attrs.append(f'style="{style_escaped}"')
            if subtitle_id:
                id_escaped = html.escape(subtitle_id, quote=True)
                attrs.append(f'id="{id_escaped}"')

            attr_str = ' ' + ' '.join(attrs) if attrs else ''
            # SECURITY: Properly escape subtitle text for HTML
            subtitle_text_escaped = html.escape(subtitle_info['text'], quote=False)
            html_parts.append(f'    <{tag}{attr_str}>{subtitle_text_escaped}</{tag}>')
    
    # Process content and insert images
    body = content_soup.find('body')
    if not body:
        body = content_soup
    
    # Get all paragraphs from the body
    paragraphs = body.find_all('p')
    
    # Process each paragraph and insert images
    for i, para in enumerate(paragraphs):
        # Add image above paragraph if exists
        if i in paragraph_image_map:
            for position, img_url in paragraph_image_map[i]:
                if position == 'above' and img_url:
                    normalized_url = normalize_image_url(img_url)
                    # Only add if not already added (to prevent duplicates)
                    # Check against normalized URLs to catch duplicates with different query params
                    if normalized_url not in added_normalized_urls:
                        added_image_urls.add(img_url)
                        added_normalized_urls.add(normalized_url)
                        # SECURITY: Properly escape URL for HTML
                        img_url_escaped = html.escape(img_url, quote=True)
                        # Use consistent image sizing (width set via CSS, height auto for aspect ratio)
                        # Alt text will be empty - output_generation will handle deduplication and processing
                        html_parts.append(f'        <img src="{img_url_escaped}" alt="" class="content-image" />')
        
        # Add paragraph (preserve formatting)
        para_str = str(para)
        html_parts.append(f'        {para_str}')
        
        # Add image below paragraph if exists
        if i in paragraph_image_map:
            for position, img_url in paragraph_image_map[i]:
                if position == 'below' and img_url:
                    normalized_url = normalize_image_url(img_url)
                    # Only add if not already added (to prevent duplicates)
                    # Check against normalized URLs to catch duplicates with different query params
                    if normalized_url not in added_normalized_urls:
                        added_image_urls.add(img_url)
                        added_normalized_urls.add(normalized_url)
                        # SECURITY: Properly escape URL for HTML
                        img_url_escaped = html.escape(img_url, quote=True)
                        # Use consistent image sizing (width set via CSS, height auto for aspect ratio)
                        # Alt text will be empty - output_generation will handle deduplication and processing
                        html_parts.append(f'        <img src="{img_url_escaped}" alt="" class="content-image" />')
    
    # Add any remaining content (non-paragraph elements like divs, sections, etc.)
    # But skip paragraphs we've already processed
    processed_paragraphs = set(paragraphs)
    for element in body.children:
        if hasattr(element, 'name') and element.name:
            if element not in processed_paragraphs and element.name not in ['script', 'style']:
                # Check if this element contains any of our processed paragraphs
                contains_processed = False
                for para in processed_paragraphs:
                    if para in element.descendants:
                        contains_processed = True
                        break
                
                # Only add if it doesn't contain processed paragraphs (to avoid duplication)
                if not contains_processed:
                    html_parts.append(f'        {str(element)}')
    
    html_parts.append('</body>')
    html_parts.append('</html>')
    
    return '\n'.join(html_parts)


def main():
    """
    Main function with default values for testing.
    """
    # Default values
    default_url = "https://www.vogue.com/article/thin-little-scarf-fall-winter-trend"
    default_filetype = "html"
    
    # Get URL from command line or use default
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = default_url
        print(f"No URL provided, using default: {url}")
        print(f"Usage: python {sys.argv[0]} <url> [filetype] [keywords...] [--include-first]")
        print(f"  keywords: Optional space-separated keywords to filter paragraphs")
        print(f"  --include-first: Always include first paragraph even if it doesn't match keywords")
    
    # Get filetype from command line or use default
    if len(sys.argv) > 2:
        filetype = sys.argv[2]
    else:
        filetype = default_filetype
        print(f"No filetype provided, using default: {filetype}")
        print(f"Supported filetypes: html, docx, pdf, md, markdown")
    
    # Get keywords and flags from command line (all arguments after filetype)
    keywords = None
    include_first_paragraph = False
    
    if len(sys.argv) > 3:
        # Check for --include-first flag
        args = sys.argv[3:]
        if '--include-first' in args:
            include_first_paragraph = True
            args = [arg for arg in args if arg != '--include-first']
        
        # Remaining arguments are keywords
        if args:
            keywords = args
            print(f"Keywords provided: {', '.join(keywords)}")
    
    if include_first_paragraph:
        print("Flag set: Always including first paragraph")
    
    try:
        output_path = process_url_to_file(
            url, 
            filetype, 
            keywords=keywords,
            include_first_paragraph=include_first_paragraph
        )
        print("\n" + "=" * 80)
        print("SUCCESS!")
        print("=" * 80)
        print(f"Output file: {output_path}")
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


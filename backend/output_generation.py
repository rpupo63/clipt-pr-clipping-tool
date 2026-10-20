#!/usr/bin/env python3
"""
Output generation functions for converting HTML to various file formats
Supports conversion to DOCX, PDF, and Markdown formats
"""

import os
import re
from pathlib import Path
from typing import Optional, Union, Dict, Set
from bs4 import BeautifulSoup
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import utilities
from logger import get_logger
from url_utils import normalize_image_url

logger = get_logger(__name__)

# Try to import PIL for image processing
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Lazy imports for optional dependencies
DOCX_IMPORT_ERROR = None
try:
    from docx import Document as DocxDocument
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_AVAILABLE = True
except ImportError as e:
    DOCX_AVAILABLE = False
    DOCX_IMPORT_ERROR = str(e)

try:
    from weasyprint import HTML
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import markdownify
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False


def _resize_image(image_bytes: bytes, target_width: int) -> tuple:
    """
    Resize an image to a target width while maintaining aspect ratio.
    
    Args:
        image_bytes: Image data as bytes
        target_width: Target width in pixels
        
    Returns:
        tuple: (resized_image_bytes, width, height) or (original_bytes, width, height) if PIL unavailable
    """
    if not PIL_AVAILABLE:
        # If PIL is not available, return original image
        # Try to get dimensions from image data if possible
        return image_bytes, None, None
    
    try:
        img = Image.open(BytesIO(image_bytes))
        original_width, original_height = img.size
        
        # Calculate new height maintaining aspect ratio
        aspect_ratio = original_height / original_width
        target_height = int(target_width * aspect_ratio)
        
        # Resize image
        resized_img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Save to bytes
        output = BytesIO()
        # Preserve format
        img_format = img.format or 'PNG'
        resized_img.save(output, format=img_format)
        output.seek(0)
        
        return output.getvalue(), target_width, target_height
    except Exception:
        # If resize fails, return original
        return image_bytes, None, None


def _process_images_in_html(html_content: str, target_width: int = 800) -> str:
    """
    Process all images in HTML: deduplicate by URL, download, and resize to consistent width.
    
    Args:
        html_content: HTML content as string
        target_width: Target width for all images in pixels (default: 800)
        
    Returns:
        str: HTML content with processed images (as data URIs or base64)
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find all image tags
    img_tags = soup.find_all('img')
    if not img_tags:
        return html_content
    
    # Collect unique image URLs (normalized for deduplication)
    image_url_map = {}  # Maps normalized URL to original URL
    normalized_to_original = {}  # Maps normalized URL to list of original URLs
    
    for img in img_tags:
        src = img.get('src', '')
        if src and src.startswith('http'):
            normalized = normalize_image_url(src)
            if normalized not in normalized_to_original:
                normalized_to_original[normalized] = []
            normalized_to_original[normalized].append(src)
            # Use the first original URL we encounter for each normalized URL
            if normalized not in image_url_map:
                image_url_map[normalized] = src
    
    # Download and process each unique image in parallel
    processed_images = {}  # Maps normalized URL to (resized_bytes, width, height)

    def download_and_process_image(normalized_url, original_url):
        """Helper function to download and process a single image."""
        try:
            from image_utils import download_image
            image_bytes, width, height = download_image(original_url)

            if image_bytes:
                # Resize to target width
                resized_bytes, new_width, new_height = _resize_image(image_bytes, target_width)
                return normalized_url, (resized_bytes, new_width, new_height)
        except Exception as e:
            logger.warning(f"Failed to download/process image {original_url}: {e}")
        return normalized_url, None

    # Use ThreadPoolExecutor for parallel downloads (max 5 concurrent downloads)
    max_workers = min(5, len(image_url_map)) if image_url_map else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_url = {
            executor.submit(download_and_process_image, norm_url, orig_url): norm_url
            for norm_url, orig_url in image_url_map.items()
        }

        # Collect results as they complete
        for future in as_completed(future_to_url):
            normalized_url, result = future.result()
            if result is not None:
                processed_images[normalized_url] = result
    
    # Replace all image tags with processed versions
    for img in img_tags:
        src = img.get('src', '')
        if src and src.startswith('http'):
            normalized = normalize_image_url(src)

            if normalized in processed_images:
                resized_bytes, new_width, new_height = processed_images[normalized]
                
                # Convert to data URI
                # Determine image format from bytes (more reliable than URL extension)
                img_format = 'png'  # Default
                if PIL_AVAILABLE:
                    try:
                        img_check = Image.open(BytesIO(resized_bytes))
                        format_map = {
                            'JPEG': 'jpeg',
                            'PNG': 'png',
                            'GIF': 'gif',
                            'WEBP': 'webp'
                        }
                        img_format = format_map.get(img_check.format, 'png')
                    except Exception:
                        # Fallback to URL-based detection
                        if src.lower().endswith(('.jpg', '.jpeg')):
                            img_format = 'jpeg'
                        elif src.lower().endswith('.gif'):
                            img_format = 'gif'
                        elif src.lower().endswith('.webp'):
                            img_format = 'webp'
                else:
                    # Fallback to URL-based detection if PIL not available
                    if src.lower().endswith(('.jpg', '.jpeg')):
                        img_format = 'jpeg'
                    elif src.lower().endswith('.gif'):
                        img_format = 'gif'
                    elif src.lower().endswith('.webp'):
                        img_format = 'webp'
                
                import base64
                base64_data = base64.b64encode(resized_bytes).decode('utf-8')
                data_uri = f'data:image/{img_format};base64,{base64_data}'
                
                # Update img tag
                img['src'] = data_uri
                if new_width:
                    img['width'] = str(new_width)
                if new_height:
                    img['height'] = str(new_height)
    
    return str(soup)


def html_to_docx(html_content: str) -> bytes:
    """
    Convert HTML content to a DOCX document
    
    Args:
        html_content: HTML content as string
        
    Returns:
        bytes: DOCX document as bytes
        
    Raises:
        ImportError: If python-docx is not available or there's a conflict with old docx package
    """
    # Process images: deduplicate, download, and resize
    html_content = _process_images_in_html(html_content, target_width=800)
    
    if not DOCX_AVAILABLE:
        error_msg = "python-docx is not available"
        if DOCX_IMPORT_ERROR:
            error_msg += f": {DOCX_IMPORT_ERROR}"
        error_msg += "\nPlease uninstall any old 'docx' package and ensure 'python-docx' is installed:"
        error_msg += "\n  pip uninstall docx"
        error_msg += "\n  pip install python-docx"
        raise ImportError(error_msg)
    
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Create DOCX document
    doc = DocxDocument()
    
    # Process body content (title h1 will be processed from body, not from <title> tag)
    body = soup.find('body') or soup
    
    def parse_style(style_str: str) -> Dict[str, str]:
        """Parse inline CSS style string into a dictionary"""
        if not style_str:
            return {}
        styles = {}
        for prop in style_str.split(';'):
            prop = prop.strip()
            if ':' in prop:
                key, value = prop.split(':', 1)
                styles[key.strip().lower()] = value.strip()
        return styles
    
    def apply_style_to_run(run, styles: Dict[str, str]):
        """Apply CSS styles to a DOCX run"""
        if not styles:
            return
        
        # Font weight
        font_weight = styles.get('font-weight', '').lower()
        if font_weight in ['bold', '700', '800', '900']:
            run.bold = True
        elif font_weight in ['normal', '400']:
            run.bold = False
        
        # Font style
        font_style = styles.get('font-style', '').lower()
        if font_style == 'italic':
            run.italic = True
        elif font_style == 'normal':
            run.italic = False
        
        # Font size
        font_size = styles.get('font-size', '')
        if font_size:
            # Try to parse font size (e.g., "12pt", "1.2em", "16px")
            size_match = re.search(r'(\d+\.?\d*)', font_size)
            if size_match:
                try:
                    size_val = float(size_match.group(1))
                    # Convert px to pt (assuming 1px = 0.75pt)
                    if 'px' in font_size:
                        size_val = size_val * 0.75
                    # em is relative, approximate as 12pt base
                    elif 'em' in font_size:
                        size_val = size_val * 12
                    run.font.size = Pt(size_val)
                except (ValueError, TypeError):
                    pass
        
        # Font family
        font_family = styles.get('font-family', '')
        if font_family:
            # Extract first font name (before comma)
            font_name = font_family.split(',')[0].strip().strip('"').strip("'")
            if font_name:
                run.font.name = font_name
    
    def process_inline_content(content, para, parent_styles=None):
        """Process inline content and create runs with formatting"""
        if parent_styles is None:
            parent_styles = {}
        
        if not hasattr(content, 'name') or content.name is None:
            # Text node - add as run
            text = str(content).strip()
            if text:
                run = para.add_run(text)
                apply_style_to_run(run, parent_styles)
            return
        
        # Get inline styles
        style_attr = content.get('style', '')
        styles = parse_style(style_attr)
        # Merge with parent styles (child styles override parent)
        combined_styles = {**parent_styles, **styles}
        
        # Process based on tag name
        tag = content.name
        
        if tag in ['strong', 'b']:
            run = para.add_run(content.get_text())
            run.bold = True
            apply_style_to_run(run, combined_styles)
        
        elif tag in ['em', 'i']:
            run = para.add_run(content.get_text())
            run.italic = True
            apply_style_to_run(run, combined_styles)
        
        elif tag in ['u', 'ins']:
            run = para.add_run(content.get_text())
            run.underline = True
            apply_style_to_run(run, combined_styles)
        
        elif tag == 'code':
            run = para.add_run(content.get_text())
            run.font.name = 'Courier New'
            run.font.size = Pt(9)
            apply_style_to_run(run, combined_styles)
        
        elif tag == 'span':
            # Span tag - process children recursively
            for child in content.children:
                process_inline_content(child, para, combined_styles)
        
        elif tag == 'a':
            # Link - process children recursively
            for child in content.children:
                process_inline_content(child, para, combined_styles)
        
        else:
            # Unknown inline tag - process children recursively
            for child in content.children:
                process_inline_content(child, para, combined_styles)
    
    def process_element(element, doc, parent_para=None):
        """Recursively process HTML elements and add to document"""
        if not hasattr(element, 'name') or element.name is None:
            # Text node
            return
        
        # Helper function to check if element is a subtitle
        def is_subtitle_element(elem):
            """Check if an element is marked as a subtitle"""
            classes = elem.get('class', [])
            class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
            element_id = elem.get('id', '')
            subtitle_patterns = ['subtitle', 'dek', 'deck', 'subheading', 'sub-heading', 'lead', 'summary', 'excerpt']
            return any(pattern in class_str.lower() for pattern in subtitle_patterns) or \
                   any(pattern in element_id.lower() for pattern in subtitle_patterns)
        
        if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # Check if h2 or h3 is actually a subtitle
            if element.name in ['h2', 'h3'] and is_subtitle_element(element):
                # Process as subtitle paragraph instead of heading
                text = element.get_text().strip()
                if text:
                    para = doc.add_paragraph()
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    style_attr = element.get('style', '')
                    styles = parse_style(style_attr)
                    if 'font-style' not in styles:
                        styles['font-style'] = 'italic'
                    for content in element.children:
                        process_inline_content(content, para, styles)
            else:
                # Regular heading (h1-h6, or h2/h3 that's not a subtitle)
                level = int(element.name[1])
                text = element.get_text().strip()
                if text:
                    heading = doc.add_heading(level=level)
                    # Process heading content to preserve formatting
                    style_attr = element.get('style', '')
                    styles = parse_style(style_attr)
                    for content in element.children:
                        process_inline_content(content, heading, styles)
                    
                    # Set alignment if specified
                    if styles.get('text-align') == 'center':
                        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif styles.get('text-align') == 'right':
                        heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        
        elif element.name == 'p':
            # Check if this paragraph is actually a subtitle
            if is_subtitle_element(element):
                # Process as subtitle
                text = element.get_text().strip()
                if text:
                    para = doc.add_paragraph()
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    style_attr = element.get('style', '')
                    styles = parse_style(style_attr)
                    if 'font-style' not in styles:
                        styles['font-style'] = 'italic'
                    for content in element.children:
                        process_inline_content(content, para, styles)
            else:
                # Regular paragraph
                text = element.get_text().strip()
                if text:
                    para = doc.add_paragraph()
                    # Get paragraph-level styles
                    style_attr = element.get('style', '')
                    styles = parse_style(style_attr)
                    
                    # Set paragraph alignment
                    if styles.get('text-align') == 'center':
                        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    elif styles.get('text-align') == 'right':
                        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    
                    # Process inline formatting
                    for content in element.children:
                        process_inline_content(content, para, styles)
        
        elif element.name == 'ul':
            for li in element.find_all('li', recursive=False):
                text = li.get_text().strip()
                if text:
                    doc.add_paragraph(text, style='List Bullet')
        
        elif element.name == 'ol':
            for li in element.find_all('li', recursive=False):
                text = li.get_text().strip()
                if text:
                    doc.add_paragraph(text, style='List Number')
        
        elif element.name == 'blockquote':
            text = element.get_text().strip()
            if text:
                para = doc.add_paragraph()
                style_attr = element.get('style', '')
                styles = parse_style(style_attr)
                for content in element.children:
                    process_inline_content(content, para, styles)
                para.style = 'Quote'
        
        elif element.name == 'pre':
            text = element.get_text()
            if text:
                para = doc.add_paragraph(text)
                para.style = 'No Spacing'
                for run in para.runs:
                    run.font.name = 'Courier New'
                    run.font.size = Pt(10)
        
        elif element.name == 'code' and (not hasattr(element.parent, 'name') or element.parent.name != 'pre'):
            # Inline code (not inside pre) - handled by process_inline_content
            pass
        
        elif element.name in ['div', 'section', 'article', 'main']:
            # Check if this is a subtitle (can be div, etc. with subtitle class/id)
            if is_subtitle_element(element):
                # Process as a subtitle paragraph with italic style and centered alignment
                text = element.get_text().strip()
                if text:
                    para = doc.add_paragraph()
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    style_attr = element.get('style', '')
                    styles = parse_style(style_attr)
                    # Default to italic if not specified
                    if 'font-style' not in styles:
                        styles['font-style'] = 'italic'
                    for content in element.children:
                        process_inline_content(content, para, styles)
            else:
                # Regular block element - process children
                for child in element.children:
                    process_element(child, doc)
        
        elif element.name == 'br':
            # Add line break
            if doc.paragraphs:
                doc.paragraphs[-1].add_run().add_break()
        
        elif element.name == 'img':
            # Handle images - images are already processed (deduplicated, downloaded, resized)
            # They should now be data URIs with consistent sizing
            img_src = element.get('src', '')
            if img_src:
                try:
                    # Check if it's a data URI (from processed images)
                    if img_src.startswith('data:image/'):
                        # Extract base64 data
                        import base64
                        header, data = img_src.split(',', 1)
                        image_bytes = base64.b64decode(data)
                        
                        # Get dimensions from img tag attributes (set during processing)
                        width_attr = element.get('width')
                        height_attr = element.get('height')
                        actual_width = None
                        actual_height = None
                        
                        if width_attr and height_attr:
                            try:
                                actual_width = int(width_attr)
                                actual_height = int(height_attr)
                            except (ValueError, TypeError):
                                pass
                        
                        # Standard DOCX content width is approximately 6.5 inches (with margins)
                        # Set image width to 1/2 of content width
                        target_width_inches = 6.5 / 2.0  # Approximately 3.25 inches
                        
                        if actual_width and actual_height:
                            # Calculate height proportionally based on aspect ratio
                            aspect_ratio = actual_height / actual_width
                            target_height_inches = target_width_inches * aspect_ratio
                            
                            # Add image to document with consistent sizing
                            para = doc.add_paragraph()
                            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = para.add_run()
                            run.add_picture(BytesIO(image_bytes), width=Inches(target_width_inches), height=Inches(target_height_inches))
                        else:
                            # If we can't get dimensions, use width only and let height scale automatically
                            para = doc.add_paragraph()
                            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            run = para.add_run()
                            # Add picture with width constraint, height will be calculated automatically
                            run.add_picture(BytesIO(image_bytes), width=Inches(target_width_inches))
                    else:
                        # Fallback: if image is still a URL (shouldn't happen after processing, but handle it)
                        # Download image and get dimensions using shared utility
                        try:
                            from image_utils import download_image
                            image_bytes, actual_width, actual_height = download_image(img_src)
                            
                            if image_bytes:
                                # Standard DOCX content width is approximately 6.5 inches (with margins)
                                # Set image width to 1/2 of content width
                                target_width_inches = 6.5 / 2.0  # Approximately 3.25 inches
                                
                                if actual_width and actual_height:
                                    # Calculate height proportionally based on aspect ratio
                                    aspect_ratio = actual_height / actual_width
                                    target_height_inches = target_width_inches * aspect_ratio
                                    
                                    # Add image to document with consistent sizing
                                    para = doc.add_paragraph()
                                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    run = para.add_run()
                                    run.add_picture(BytesIO(image_bytes), width=Inches(target_width_inches), height=Inches(target_height_inches))
                                else:
                                    # If we can't get dimensions, use width only and let height scale automatically
                                    para = doc.add_paragraph()
                                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                    run = para.add_run()
                                    # Add picture with width constraint, height will be calculated automatically
                                    run.add_picture(BytesIO(image_bytes), width=Inches(target_width_inches))
                        except Exception:
                            # If download fails, skip image
                            pass
                        
                except Exception as e:
                    # If image processing fails, skip it
                    # Could optionally add a placeholder or log the error
                    pass
    
    # Process all direct children of body
    for child in body.children:
        process_element(child, doc)
    
    # Save to BytesIO and return bytes
    from io import BytesIO
    docx_buffer = BytesIO()
    doc.save(docx_buffer)
    return docx_buffer.getvalue()


def html_to_pdf(html_content: str) -> bytes:
    """
    Convert HTML content to a PDF document
    
    Args:
        html_content: HTML content as string
        
    Returns:
        bytes: PDF document as bytes
        
    Raises:
        ImportError: If weasyprint is not available
    """
    # Process images: deduplicate, download, and resize
    html_content = _process_images_in_html(html_content, target_width=800)
    
    if not PDF_AVAILABLE:
        raise ImportError("weasyprint is not available. Please install it: pip install weasyprint")
    
    # Convert HTML to PDF using WeasyPrint and return as bytes
    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


def html_to_markdown(html_content: str) -> str:
    """
    Convert HTML content to a Markdown document
    
    Args:
        html_content: HTML content as string
        
    Returns:
        str: Markdown content as string
        
    Raises:
        ImportError: If markdownify is not available
    """
    # Process images: deduplicate, download, and resize
    html_content = _process_images_in_html(html_content, target_width=800)
    
    if not MARKDOWN_AVAILABLE:
        raise ImportError("markdownify is not available. Please install it: pip install markdownify")
    
    # Parse HTML to preserve image dimensions
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Process images to preserve dimensions in markdown
    for img in soup.find_all('img'):
        src = img.get('src', '')
        alt = img.get('alt', '')
        width = img.get('width')
        height = img.get('height')
        
        # Create markdown image syntax with dimensions if available
        if width and height:
            # Markdown doesn't natively support dimensions, but we can add them as HTML
            # or use a format that some markdown processors support
            img.replace_with(f'<img src="{src}" alt="{alt}" width="{width}" height="{height}" />')
        elif src:
            # Standard markdown image syntax
            img.replace_with(f'![{alt}]({src})')
    
    # Convert HTML to Markdown
    markdown_content = markdownify.markdownify(
        str(soup),
        heading_style="ATX",  # Use # style headings
        bullets="-",  # Use - for bullet points
        strip=['script', 'style']  # Strip script and style tags
    )
    
    return markdown_content


def convert_html(html_content: str, filetype: str) -> Union[bytes, str]:
    """
    Convert HTML content to the specified file format
    
    Args:
        html_content: HTML content as string
        filetype: Desired output format ('docx', 'pdf', 'md', or 'markdown')
        
    Returns:
        bytes: For binary formats (docx, pdf)
        str: For text formats (md, markdown)
        
    Raises:
        ValueError: If filetype is not supported
    """
    # Normalize filetype (case-insensitive)
    filetype_lower = filetype.lower().strip()
    
    # Route to appropriate conversion function
    if filetype_lower in ['docx', 'doc']:
        return html_to_docx(html_content)
    elif filetype_lower == 'pdf':
        return html_to_pdf(html_content)
    elif filetype_lower in ['md', 'markdown']:
        return html_to_markdown(html_content)
    else:
        raise ValueError(
            f"Unsupported filetype: {filetype}. "
            f"Supported formats: 'docx', 'pdf', 'md', 'markdown'"
        )


def main():
    """
    Example usage of the conversion functions
    """
    import sys

    html_file = "scraped_page.html"

    if not os.path.exists(html_file):
        logger.error(f"Error: {html_file} not found")
        return

    # Read HTML content
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    logger.info("Converting HTML to various formats...")
    logger.info("Using unified convert_html function:")

    # Convert to DOCX
    logger.info("Converting to DOCX...")
    try:
        docx_content = convert_html(html_content, 'docx')
        docx_file = str(Path(html_file).with_suffix('.docx'))
        with open(docx_file, 'wb') as f:
            f.write(docx_content)
        logger.info(f"✓ DOCX saved to: {docx_file}")
    except Exception as e:
        logger.error(f"✗ Error converting to DOCX: {e}", exc_info=True)

    # Convert to PDF
    logger.info("Converting to PDF...")
    try:
        pdf_content = convert_html(html_content, 'pdf')
        pdf_file = str(Path(html_file).with_suffix('.pdf'))
        with open(pdf_file, 'wb') as f:
            f.write(pdf_content)
        logger.info(f"✓ PDF saved to: {pdf_file}")
    except Exception as e:
        logger.error(f"✗ Error converting to PDF: {e}", exc_info=True)

    # Convert to Markdown
    logger.info("Converting to Markdown...")
    try:
        md_content = convert_html(html_content, 'md')
        md_file = str(Path(html_file).with_suffix('.md'))
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(md_content)
        logger.info(f"✓ Markdown saved to: {md_file}")
    except Exception as e:
        logger.error(f"✗ Error converting to Markdown: {e}", exc_info=True)


if __name__ == "__main__":
    import sys
    main()


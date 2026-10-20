#!/usr/bin/env python3
"""
Selenium web scraper with uBlock Origin ad-blocking
Waits for page to fully render and outputs HTML without ads
"""

import time
import sys
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# Import utilities
from constants import PageConfig
from logger import get_logger
from url_utils import validate_url

logger = get_logger(__name__)


def download_ublock_extension():
    """
    Download uBlock Origin extension.
    Returns the path to the .crx file
    """
    import urllib.request
    import os
    
    # uBlock Origin Chrome extension ID and download URL
    extension_id = "cjpalhdlnbpafiamejdnhcphjbkeiagm"
    
    # For a more reliable method, we'll use a pre-built extension path
    # You can download it from: https://github.com/gorhill/uBlock/releases
    logger.info("Note: Download uBlock Origin from Chrome Web Store or GitHub releases")
    logger.info("For this script, we'll use Chrome's built-in extension loading")

    return None


@contextmanager
def chrome_driver_context(options: Optional[Options] = None):
    """
    Context manager for Chrome WebDriver with proper resource cleanup.

    Args:
        options: Chrome options to use

    Yields:
        webdriver.Chrome: Chrome driver instance

    Example:
        >>> with chrome_driver_context() as driver:
        ...     driver.get("https://example.com")
        ...     html = driver.page_source
    """
    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        yield driver
    finally:
        if driver is not None:
            try:
                driver.quit()
                logger.debug("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")


def create_chrome_options() -> Options:
    """
    Create Chrome options with uBlock Origin if available.

    Returns:
        Options: Configured Chrome options
    """
    chrome_options = Options()

    # Basic headless configuration
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    # Attempt to load uBlock Origin extension
    # SECURITY: Use Path for safe path handling, validate extension directory
    ublock_path = Path("./uBlock0.chromium/uBlock0.chromium")

    try:
        # Resolve to absolute path and validate
        ublock_absolute = ublock_path.resolve()

        # Security check: ensure path exists and is a directory
        if ublock_absolute.exists() and ublock_absolute.is_dir():
            # Additional security: ensure it's not a symlink to unexpected location
            if not ublock_absolute.is_symlink():
                chrome_options.add_argument(f'--load-extension={ublock_absolute}')
                logger.info("✓ uBlock Origin loaded")
            else:
                logger.warning("⚠ uBlock path is a symlink - skipping for security")
        else:
            logger.warning("⚠ uBlock Origin not found - continuing without ad-blocker")
            logger.info(f"  Looking for: {ublock_absolute}")
            logger.info("  Download from: https://github.com/gorhill/uBlock/releases")
    except Exception as e:
        logger.warning(f"Could not load uBlock Origin: {e}")

    return chrome_options


def scrape_page(
    url: str,
    wait_time: float = None,
    timeout: int = None
) -> Optional[str]:
    """
    Scrape a webpage with ad-blocking and security validation.

    Args:
        url: The URL to scrape
        wait_time: Time to wait for page to fully render (seconds)
        timeout: Maximum time to wait for page load (seconds)

    Returns:
        str: The HTML content of the page, or None if scraping fails

    Raises:
        ValueError: If URL validation fails
    """
    if wait_time is None:
        wait_time = PageConfig.LOAD_WAIT_TIME
    if timeout is None:
        timeout = PageConfig.PAGE_TIMEOUT

    # SECURITY: Validate URL to prevent SSRF attacks
    is_valid, error_msg = validate_url(url)
    if not is_valid:
        logger.error(f"URL validation failed: {error_msg}")
        raise ValueError(f"Invalid URL: {error_msg}")

    try:
        logger.info(f"Initializing browser with ad-blocker...")
        chrome_options = create_chrome_options()

        # Use context manager for proper resource cleanup
        with chrome_driver_context(chrome_options) as driver:
            logger.info(f"Loading URL: {url}")
            driver.set_page_load_timeout(timeout)
            driver.get(url)

            # Wait for the page to load
            logger.info(f"Waiting {wait_time} second(s) for page to render...")
            time.sleep(wait_time)

            # Wait for body element to be present
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Get the page source (HTML)
            html_content = driver.page_source

            logger.info(f"✓ Successfully scraped {len(html_content)} characters")
            return html_content

    except ValueError:
        # Re-raise validation errors
        raise
    except Exception as e:
        logger.error(f"Error during scraping: {e}", exc_info=True)
        return None


def site_preprocessing(url):
    """Main function"""
    # Example URL - replace with your target
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "https://www.vogue.com/article/thin-little-scarf-fall-winter-trend"
        logger.info(f"No URL provided, using default: {url}")
        logger.info(f"Usage: python {sys.argv[0]} <url>")

    # Scrape the page
    html = scrape_page(url, wait_time=1)

    if html:
        # Output the HTML
        logger.info("=" * 80)
        logger.info("HTML OUTPUT:")
        logger.info("=" * 80)
        logger.info(html)

        # Optionally save to file
        output_file = "scraped_page.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"✓ HTML saved to: {output_file}")
    else:
        logger.error("Failed to scrape the page")
        sys.exit(1)


if __name__ == "__main__":
    site_preprocessing()
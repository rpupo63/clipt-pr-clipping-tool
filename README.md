# Clipt - Web Content Extraction and Clipping Tool

Clipt is a powerful backend service for extracting and formatting web content into clean, structured documents. It intelligently extracts articles from web pages, removes ads and clutter, and outputs them in multiple formats (HTML, DOCX, PDF, Markdown).

## Features

- **Ad-Free Scraping**: Uses Selenium with uBlock Origin to scrape clean content without ads
- **Intelligent Content Extraction**: AI-powered extraction using Firecrawl and OpenAI to identify article boundaries
- **Multi-Format Output**: Generate documents in HTML, DOCX, PDF, or Markdown formats
- **Logo & Header Extraction**: Automatically extracts site logos, titles, and subtitles
- **Image Processing**: Finds and embeds relevant images from articles
- **Keyword Filtering**: Filter paragraphs by keywords while optionally preserving the first paragraph
- **REST API**: Flask-based API for easy integration
- **Security Hardened**: SSRF protection, XSS prevention, secure file handling

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Command Line Interface](#command-line-interface)
  - [REST API](#rest-api)
- [Architecture & Methodologies](#architecture--methodologies)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## Installation

### Prerequisites

- Python 3.8 or higher
- Chrome/Chromium browser (for Selenium)
- ChromeDriver (automatically managed by Selenium 4.x)

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd Clipt
```

### Step 2: Set Up Python Virtual Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Install System Dependencies (if needed)

For PDF generation, you may need additional system libraries:

**Ubuntu/Debian:**

```bash
sudo apt-get install libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

**macOS:**

```bash
brew install cairo pango gdk-pixbuf libffi
```

**Arch Linux:**

```bash
sudo pacman -S cairo pango gdk-pixbuf2 libffi
```

## Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```bash
cd backend
touch .env
```

Add the following variables (optional API keys for enhanced features):

```env
# Optional: For AI-powered content extraction
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

**Note:** The application will work without these API keys, but AI-powered content extraction will be disabled. You can get API keys from:

- [Firecrawl](https://www.firecrawl.dev/) - For advanced web scraping
- [OpenAI](https://platform.openai.com/) - For intelligent content boundary detection

### Validate Configuration

The application validates configuration at startup. You can test it:

```bash
python -c "from config import Config; Config.validate()"
```

## Usage

### Command Line Interface

#### Basic Usage

Process a URL and generate an HTML file:

```bash
python clipping_logic.py "https://example.com/article"
```

#### Advanced Options

```bash
# Specify output format
python clipping_logic.py "https://example.com/article" pdf

# With keyword filtering
python clipping_logic.py "https://example.com/article" html technology AI "machine learning"

# Always include first paragraph
python clipping_logic.py "https://example.com/article" html technology AI --include-first
```

**Usage:**

```bash
python clipping_logic.py <url> [filetype] [keywords...] [--include-first]
```

**Parameters:**

- `url`: URL to process (required, first positional argument)
- `filetype`: Output format - `html`, `docx`, `pdf`, `md`, or `markdown` (optional, default: `html`)
- `keywords`: Space-separated keywords to filter paragraphs (optional)
- `--include-first`: Always include first paragraph even if no keyword match (optional flag)

#### Using the Python Module Directly

```python
from clipping_logic import process_url_to_file

# Basic usage
output_path = process_url_to_file(
    url="https://example.com/article",
    filetype="html"
)

# With keyword filtering
output_path = process_url_to_file(
    url="https://example.com/article",
    filetype="pdf",
    keywords=["technology", "AI"],
    include_first_paragraph=True
)
```

### REST API

#### Start the Server

```bash
cd backend
python main.py
```

The API will be available at `http://localhost:5000` (default port: 5000)

#### API Endpoints

##### Process URL

**POST** `/api/process`

Process a URL and generate output in the specified format.

**Request Body:**

```json
{
  "url": "https://example.com/article",
  "filetype": "html",
  "keywords": ["keyword1", "keyword2"],
  "include_first_paragraph": false,
  "output_file": "output.html",
  "return_file": false
}
```

**Parameters:**

- `url` (required): URL to process
- `filetype` (optional): Output format - `html`, `docx`, `pdf`, `md`, `markdown` (default: `html`)
- `keywords` (optional): Array of keywords to filter paragraphs
- `include_first_paragraph` (optional): Always include first paragraph (default: `false`)
- `output_file` (optional): Custom output filename
- `return_file` (optional): If `true`, returns file directly; if `false`, returns JSON with file path (default: `false`)

**Response (JSON mode):**

```json
{
  "success": true,
  "output_path": "/path/to/output/file.html",
  "message": "Processing completed successfully"
}
```

**Response (File mode):**
Returns the file directly as a download.

##### Health Check

**GET** `/api/health`

Check if the API is running.

**Response:**

```json
{
  "status": "healthy",
  "service": "Clipt API",
  "version": "1.0.0"
}
```

##### API Documentation

**GET** `/`

Returns API documentation in JSON format.

#### Example API Calls

**Using curl:**

```bash
# Process URL and get JSON response
curl -X POST http://localhost:5000/api/process \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/article",
    "filetype": "pdf",
    "keywords": ["technology"],
    "return_file": false
  }'

# Process URL and download file directly
curl -X POST http://localhost:5000/api/process \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/article",
    "filetype": "pdf",
    "return_file": true
  }' \
  --output article.pdf
```

**Using Python requests:**

```python
import requests

response = requests.post('http://localhost:5000/api/process', json={
    'url': 'https://example.com/article',
    'filetype': 'pdf',
    'keywords': ['technology', 'AI'],
    'include_first_paragraph': True,
    'return_file': True
})

with open('article.pdf', 'wb') as f:
    f.write(response.content)
```

## Architecture & Methodologies

### Processing Pipeline

The clipping extraction process follows these steps:

1. **Web Scraping with Ad-Blocking** (`site_preprocessing.py`)

   - Uses Selenium WebDriver with Chrome
   - Loads uBlock Origin extension to block ads and trackers
   - Waits for page to fully render
   - Returns clean HTML content

2. **Logo Extraction** (`logo_extraction.py`)

   - Searches for logo using multiple heuristics:
     - Common logo selectors (`<img>` with "logo" in class/id/alt)
     - Open Graph images
     - Favicon fallback
   - Validates logo size (20-500px) and filters out decorative images
   - Returns absolute URL and element information

3. **Header Extraction** (`header_extraction.py`)

   - Extracts title using semantic HTML (`<h1>`, `<title>`, Open Graph)
   - Extracts subtitle from elements near the title
   - Validates subtitle position (must be within 5 DOM elements of title)
   - Preserves formatting information (classes, styles, HTML structure)

4. **Content Extraction** (`content_extraction.py`)

   - **AI-Powered Method** (if API keys available):
     - Uses Firecrawl to scrape and convert to markdown
     - Uses OpenAI to identify first and last contentful sentences
     - Finds the smallest DOM container containing both sentences
     - Extracts all content within that container
   - **Heuristic Fallback**:
     - Searches for main content containers (`<main>`, `<article>`, etc.)
     - Filters out navigation, headers, footers, and ads
     - Extracts paragraphs and preserves structure

5. **Image Processing** (`image_utils.py`, `positional_extraction.py`)

   - Finds images near extracted paragraphs
   - Searches within 5 DOM elements of each paragraph
   - Downloads and processes images:
     - Resizes to target width (800px) while maintaining aspect ratio
     - Converts to appropriate format
     - Embeds as base64 data URIs or saves as files

6. **Output Generation** (`output_generation.py`)
   - Converts processed HTML to requested format:
     - **HTML**: Clean, formatted HTML with embedded images
     - **DOCX**: Microsoft Word document with proper formatting
     - **PDF**: PDF document using WeasyPrint
     - **Markdown**: Markdown format using markdownify

### Key Methodologies

#### 1. Ad-Free Scraping

- **Technology**: Selenium WebDriver + uBlock Origin
- **Why**: Many websites load content dynamically and contain ads/trackers
- **Method**: Loads extension before page load, waits for full render, extracts clean HTML

#### 2. AI-Powered Content Boundary Detection

- **Technology**: Firecrawl (scraping) + OpenAI GPT (analysis)
- **Why**: Heuristic extraction can include navigation, ads, or miss content boundaries
- **Method**:
  1. Firecrawl converts page to clean markdown
  2. OpenAI analyzes markdown to identify first/last contentful sentences
  3. System finds DOM elements containing these sentences
  4. Extracts smallest container containing both boundaries

#### 3. Semantic HTML Parsing

- **Technology**: BeautifulSoup4 with semantic selectors
- **Why**: Modern websites use semantic HTML (`<main>`, `<article>`, ARIA roles)
- **Method**: Prioritizes semantic containers over generic `<div>` elements

#### 4. Image-Text Association

- **Technology**: DOM traversal and positional analysis
- **Why**: Images are often near related paragraphs but not directly nested
- **Method**: Searches within 5 DOM elements of each paragraph for relevant images

#### 5. Keyword-Based Filtering

- **Technology**: Text matching with optional first-paragraph preservation
- **Why**: Users may only want specific sections of long articles
- **Method**: Filters paragraphs containing keywords, optionally preserves first paragraph for context

### Security Features

- **SSRF Protection**: Validates URLs before requests, blocks private IPs and localhost
- **XSS Prevention**: HTML escaping for user-generated content
- **Secure File Handling**: Uses temporary directories with unique filenames
- **Resource Management**: Context managers for WebDriver, connection pooling, retry logic
- **Input Validation**: Validates filetypes, keywords, and other inputs

## Project Structure

```
Clipt/
├── backend/
│   ├── main.py                 # Flask API server
│   ├── clipping_logic.py       # Main processing pipeline
│   ├── site_preprocessing.py   # Selenium scraping with ad-blocking
│   ├── logo_extraction.py      # Logo detection and extraction
│   ├── header_extraction.py    # Title/subtitle extraction
│   ├── content_extraction.py   # Main content extraction
│   ├── positional_extraction.py # Image positioning logic
│   ├── find_first_and_last_sentences.py # AI-powered boundary detection
│   ├── image_utils.py          # Image processing utilities
│   ├── output_generation.py    # Format conversion (HTML/DOCX/PDF/MD)
│   ├── config.py               # Configuration management
│   ├── constants.py            # Centralized constants
│   ├── logger.py               # Logging framework
│   ├── url_utils.py            # URL validation and normalization
│   ├── network_utils.py        # HTTP session with retry logic
│   ├── requirements.txt        # Python dependencies
│   └── uBlock0.chromium/       # uBlock Origin extension
├── frontend/                   # React frontend (optional)
└── README.md                   # This file
```

## Troubleshooting

### Common Issues

#### 1. ChromeDriver Not Found

**Error:** `selenium.common.exceptions.WebDriverException: Message: 'chromedriver' executable needs to be in PATH`

**Solution:** Selenium 4.x should manage ChromeDriver automatically. If issues persist:

```bash
# Install ChromeDriver manually
# Ubuntu/Debian
sudo apt-get install chromium-chromedriver

# macOS
brew install chromedriver

# Or download from https://chromedriver.chromium.org/
```

#### 2. PIL/Pillow Import Errors

**Error:** `ImportError: cannot import name 'Image' from 'PIL'`

**Solution:**

```bash
pip install --upgrade Pillow
```

#### 3. WeasyPrint PDF Generation Fails

**Error:** PDF generation fails with system library errors

**Solution:** Install required system libraries (see Installation section)

#### 4. API Keys Not Working

**Error:** `FIRECRAWL_API_KEY not found` or `OPENAI_API_KEY not found`

**Solution:**

- Ensure `.env` file exists in `backend/` directory
- Check that keys are correctly formatted (no quotes, no extra spaces)
- Verify API keys are valid and have sufficient credits

#### 5. Memory Issues with Large Pages

**Error:** Out of memory errors when processing large pages

**Solution:**

- The system has built-in size limits (10MB for images)
- For very large pages, consider using keyword filtering to reduce content
- Monitor system resources and adjust `MAX_SIZE` in `constants.py` if needed

#### 6. Timeout Errors

**Error:** `TimeoutException` or connection timeouts

**Solution:**

- Increase timeout values in `constants.py`:
  - `PageConfig.PAGE_TIMEOUT`
  - `NetworkConfig.DEFAULT_TIMEOUT`
- Check network connectivity
- Some sites may block automated access

### Debug Mode

Enable verbose logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Or set environment variable:

```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Getting Help

- Check logs in the console output
- Review `backend/REFACTORING_SUMMARY.md` for known issues
- Ensure all dependencies are installed: `pip install -r requirements.txt`

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]

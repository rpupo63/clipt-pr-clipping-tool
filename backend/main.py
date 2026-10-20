#!/usr/bin/env python3
"""
Flask API for the Clipt web clipping service.
Exposes the URL processing logic as a REST API endpoint.
"""

from flask import Flask, request, jsonify, send_file
import os
import sys
import traceback
from clipping_logic import process_url_to_file

# Import utilities
from config import Config
from logger import get_logger

# Try to import CORS, but continue if not available
try:
    from flask_cors import CORS
    cors_available = True
except ImportError:
    cors_available = False

# Set up logging
logger = get_logger(__name__)

# SECURITY: Validate configuration at startup
try:
    # Validate configuration (optional keys)
    # Set strict=True if you want to require all API keys at startup
    Config.validate(strict=False)
    logger.info("Configuration validated successfully")
except EnvironmentError as e:
    logger.error(f"Configuration validation failed: {e}")
    logger.error("Application may have limited functionality")
    # Don't exit - allow app to run with degraded functionality
    # If you want strict validation, uncomment the next line:
    # sys.exit(1)

app = Flask(__name__)

# Enable CORS if available (useful for frontend integration)
if cors_available:
    CORS(app)
    logger.info("CORS enabled")
else:
    logger.warning("CORS not available - install flask-cors for frontend integration")

@app.route('/api/process', methods=['POST'])
def process():
    """
    Process a URL and generate output in the specified format.

    Request JSON:
    {
        "url": "https://example.com/article",
        "filetype": "html",  // optional, defaults to "html". Options: html, docx, pdf, md, markdown
        "keywords": ["keyword1", "keyword2"],  // optional, filter paragraphs by keywords
        "include_first_paragraph": false,  // optional, always include first paragraph even if no keyword match
        "output_file": "output.html",  // optional, custom output filename
        "return_file": false  // optional, if true returns file directly instead of JSON
    }

    Response JSON (if return_file=false):
    {
        "success": true,
        "output_path": "path/to/output/file.html",
        "message": "Processing completed successfully"
    }

    Or returns the file directly if return_file=true
    """
    try:
        # Get JSON data from request
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body must be JSON'
            }), 400

        # Validate required parameters
        url = data.get('url')
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400

        # Get optional parameters with defaults
        filetype = data.get('filetype', 'html')
        keywords = data.get('keywords', None)
        include_first_paragraph = data.get('include_first_paragraph', False)
        output_file = data.get('output_file', None)
        return_file = data.get('return_file', False)

        # Validate filetype
        valid_filetypes = ['html', 'docx', 'pdf', 'md', 'markdown']
        if filetype.lower() not in valid_filetypes:
            return jsonify({
                'success': False,
                'error': f'Invalid filetype. Must be one of: {", ".join(valid_filetypes)}'
            }), 400

        # Validate keywords is a list if provided
        if keywords is not None and not isinstance(keywords, list):
            return jsonify({
                'success': False,
                'error': 'Keywords must be a list of strings'
            }), 400

        # Process the URL
        output_path = process_url_to_file(
            url=url,
            filetype=filetype,
            output_file=output_file,
            keywords=keywords,
            include_first_paragraph=include_first_paragraph
        )

        # Return file directly if requested
        if return_file:
            if not os.path.exists(output_path):
                return jsonify({
                    'success': False,
                    'error': f'Output file not found: {output_path}'
                }), 500

            return send_file(
                output_path,
                as_attachment=True,
                download_name=os.path.basename(output_path)
            )

        # Otherwise return JSON with file path
        return jsonify({
            'success': True,
            'output_path': output_path,
            'message': 'Processing completed successfully'
        }), 200

    except Exception as e:
        # SECURITY: Log full error server-side, send generic message to client
        error_trace = traceback.format_exc()
        logger.error(f"Error processing request: {error_trace}")

        # Don't expose internal details to client in production
        # Only send generic error message
        return jsonify({
            'success': False,
            'error': 'An error occurred processing your request. Please check your input and try again.',
            'error_type': type(e).__name__  # Only expose error type, not details
        }), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Clipt API',
        'version': '1.0.0'
    }), 200


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with API documentation"""
    return jsonify({
        'service': 'Clipt API',
        'version': '1.0.0',
        'endpoints': {
            '/api/process': {
                'method': 'POST',
                'description': 'Process a URL and extract content',
                'parameters': {
                    'url': 'string (required) - URL to process',
                    'filetype': 'string (optional) - Output format: html, docx, pdf, md, markdown. Default: html',
                    'keywords': 'array (optional) - List of keywords to filter paragraphs',
                    'include_first_paragraph': 'boolean (optional) - Always include first paragraph. Default: false',
                    'output_file': 'string (optional) - Custom output filename',
                    'return_file': 'boolean (optional) - Return file directly. Default: false'
                }
            },
            '/api/health': {
                'method': 'GET',
                'description': 'Health check endpoint'
            }
        }
    }), 200


if __name__ == '__main__':
    # Run the Flask app
    # In production, use a proper WSGI server like gunicorn
    app.run(debug=True, host='0.0.0.0', port=5000)

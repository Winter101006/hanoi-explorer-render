"""Run the web application from any working directory."""
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from project.bot.src.web.app import create_app

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0' if 'PORT' in os.environ else '127.0.0.1'
    create_app().run(host=host, port=port, debug=False)

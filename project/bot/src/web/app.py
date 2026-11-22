"""Flask factory with startup initialization for semantic search."""
import os
import sys
import logging
from pathlib import Path

# Keep the original direct app.py entry point usable.
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, render_template
from project.bot.src.chatbot.config import BOT_DIR, load_settings
from project.bot.src.web.services.chat_service import ChatService, IndexUnavailable
from project.bot.src.web.routes.chat_route import chat_bp


def create_app(settings=None, service=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
    app.extensions['chat_service'] = service or ChatService(settings or load_settings())
    if service is None:
        try:
            app.extensions['chat_service'].retriever.warm_up()
            app.logger.info('Embedding model and retrieval index ready')
        except IndexUnavailable as error:
            app.logger.warning('Starting with search unavailable: %s', error)
    app.register_blueprint(chat_bp)

    @app.get('/')
    def home():
        return render_template('index.html')

    @app.get('/guide')
    def guide():
        return app.response_class((BOT_DIR / 'README.md').read_text(encoding='utf-8'), mimetype='text/plain')

    @app.errorhandler(413)
    def oversized(_):
        return {'status': 'error', 'reply': 'Yêu cầu quá lớn.', 'places': []}, 413

    @app.errorhandler(404)
    def not_found(_):
        return render_template('index.html'), 404

    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0' if 'PORT' in os.environ else '127.0.0.1'
    create_app().run(host=host, port=port, debug=False)

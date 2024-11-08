import logging
import ssl
from flask import Flask, request, abort
from telebot import types, custom_filters
from shedule import start_scheduler
from config import BOT_TOKEN, WEBHOOK_URL, DEBUG, PORT, SSL_CERT, SSL_PRIV, SERVER_HOST, SERVER_PORT, SECRET_TOKEN
from bot import get_bot_instance
from telebot.states.sync.middleware import StateMiddleware
import handlers.start
from threading import Thread

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
app = Flask(__name__)
bot = get_bot_instance()


@app.route('/' + SECRET_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return ''
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            return '', 500
    else:
        logger.warning("Received non-JSON request")
        abort(403)


@app.route('/health', methods=['GET'])
def health_check():
    return 'OK'


@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    try:
        bot.remove_webhook()
        webhook_info = bot.set_webhook(
            url=WEBHOOK_URL + SECRET_TOKEN,
            certificate=open(SSL_CERT, 'rb')
        )
        if webhook_info:
            logger.info(f"Webhook was set: {WEBHOOK_URL}")
            # Перезапускаем приложение в режиме webhook
            restart_in_webhook_mode()
            return "Webhook set successfully!", 200
        else:
            logger.error("Failed to set webhook")
            return "Failed to set webhook", 500
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return f"Error: {str(e)}", 500


@app.route('/webhook_info', methods=['GET'])
def get_webhook_info():
    info = bot.get_webhook_info()
    return {
        'url': info.url,
        'has_custom_certificate': info.has_custom_certificate,
        'pending_update_count': info.pending_update_count,
        'last_error_date': info.last_error_date,
        'last_error_message': info.last_error_message
    }


def run_flask():
    """Запуск Flask сервера"""
    app.run(
        host=SERVER_HOST,
        port=SERVER_PORT,
        ssl_context=(SSL_CERT, SSL_PRIV),
        debug=False
    )


def run_polling():
    """Запуск бота в режиме long polling"""
    logger.info("Starting bot in polling mode...")
    bot.infinity_polling()


def restart_in_webhook_mode():
    """Перезапуск в режиме webhook"""
    bot.remove_webhook()
    bot.set_webhook(
        url=WEBHOOK_URL + SECRET_TOKEN,
        certificate=open(SSL_CERT, 'rb')
    )


if __name__ == '__main__':
    # Инициализация
    start_scheduler()
    bot.add_custom_filter(custom_filters.StateFilter(bot))
    bot.setup_middleware(StateMiddleware(bot))

    # Проверяем наличие вебхука
    webhook_info = bot.get_webhook_info()

    if webhook_info.url:
        logger.info(f"Starting in webhook mode. Webhook URL: {webhook_info.url}")
        run_flask()
    else:
        logger.info("No webhook set. Starting in polling mode with Flask server...")
        # Запускаем Flask сервер в отдельном потоке
        flask_thread = Thread(target=run_flask)
        flask_thread.start()

        # Запускаем long polling в основном потоке
        run_polling()
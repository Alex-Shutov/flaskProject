import logging
import ssl
from flask import Flask, request, abort
from telebot import types, custom_filters
from telebot.storage import StateRedisStorage
from shedule import start_scheduler
from config import BOT_TOKEN, WEBHOOK_URL, DEBUG, PORT, SSL_CERT, SSL_PRIV, SERVER_HOST, SERVER_PORT, SECRET_TOKEN
from bot import get_bot_instance
from telebot.states.sync.middleware import StateMiddleware
from telebot.handler_backends import State, StatesGroup
import handlers.start

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
            logger.info(f"Received webhook data: {json_string[:200]}...")

            update = types.Update.de_json(json_string)

            bot.process_new_updates([update])
            return ''
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            logger.exception(e)
            return '', 500
    else:
        logger.warning(f"Received non-JSON request with content-type: {request.headers.get('content-type')}")
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
            return "Webhook successfully set! Please restart the bot.", 200
        else:
            logger.error("Failed to set webhook")
            return "Failed to set webhook", 500
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return f"Error: {str(e)}", 500


@app.route('/remove_webhook', methods=['GET', 'POST'])
def remove_webhook():
    bot.remove_webhook()
    return "Webhook removed", 200




if __name__ == '__main__':
    # Инициализация
    logger.info('Starting bot initialization...')
    start_scheduler()


    # Проверяем, установлен ли вебхук
    webhook_info = bot.get_webhook_info()
    logger.info('Checking webhook info...')

    if webhook_info.url:
        logger.info(f"Bot is running in webhook mode: {webhook_info.url}")
        app.run(
            host=SERVER_HOST,
            port=SERVER_PORT,
            ssl_context=(SSL_CERT, SSL_PRIV),
            debug=False
        )
    else:
        logger.info("No webhook set. Starting bot in polling mode...")
        bot.polling(none_stop=True)
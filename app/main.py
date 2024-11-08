import logging
import ssl

from flask import Flask, request, abort
from telebot import types,custom_filters

from shedule import start_scheduler
from config import BOT_TOKEN, WEBHOOK_URL, DEBUG, PORT, SSL_CERT, SSL_PRIV, SERVER_HOST, SERVER_PORT, SECRET_TOKEN
from bot import get_bot_instance
from telebot.states.sync.middleware import StateMiddleware
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

# Регистрация вебхука
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    bot.remove_webhook()

    webhook_info = bot.set_webhook(
        url=WEBHOOK_URL + SECRET_TOKEN,
        certificate=open(SSL_CERT, 'rb')  # Используем самоподписанный сертификат
    )
    if webhook_info:
        logger.info(f"Webhook was set: {WEBHOOK_URL}")
        return True
    else:
        logger.error("Failed to set webhook")
        return False



@app.route('/remove_webhook', methods=['GET', 'POST'])
def remove_webhook():
    bot.remove_webhook()
    return "Webhook removed", 200

if __name__ == '__main__':
    # Проверяем, установлен ли вебхук
    start_scheduler()
    webhook_info = bot.get_webhook_info()
    bot.add_custom_filter(custom_filters.StateFilter(bot))


    bot.setup_middleware(StateMiddleware(bot))
    if webhook_info.url:
        print(f"Бот работает через вебхук: {webhook_info.url}")
        # context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        # context.load_cert_chain(SSL_CERT, SSL_PRIV)
        app.run(
            host=SERVER_HOST,
            port=SERVER_PORT,
            ssl_context=(SSL_CERT, SSL_PRIV),
            debug=False
        )
    else:
        print("Вебхук не установлен. Запуск бота в режиме long polling.")
        # bot.remove_webhook()
        bot.polling( none_stop=True)

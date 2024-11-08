import ssl

from flask import Flask, request, abort
from telebot import types,custom_filters

from shedule import start_scheduler
from config import BOT_TOKEN, WEBHOOK_URL, DEBUG, PORT, SSL_CERT, SSL_PRIV, SERVER_HOST, SERVER_PORT, SECRET_TOKEN
from bot import get_bot_instance
from telebot.states.sync.middleware import StateMiddleware
import handlers.start

app = Flask(__name__)
bot = get_bot_instance()

@app.route('/webhook/' + SECRET_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        abort(403)


# Регистрация вебхука
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    bot.remove_webhook()

    # Устанавливаем новый вебхук
    webhook_info = bot.set_webhook(
        url=WEBHOOK_URL,
        certificate=open(SSL_CERT, 'r'),
    )

    return f'Webhook установлен: {webhook_info}'


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
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.load_cert_chain(SSL_CERT, SSL_PRIV)
        app.run(
            host=SERVER_HOST,
            port=SERVER_PORT,
            ssl_context=context,
            debug=False
        )
    else:
        print("Вебхук не установлен. Запуск бота в режиме long polling.")
        # bot.remove_webhook()
        bot.polling( none_stop=True)

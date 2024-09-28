from flask import Flask, request
from telebot import types
from config import BOT_TOKEN, WEBHOOK_URL, DEBUG, PORT
from bot import get_bot_instance
import handlers

app = Flask(__name__)
bot = get_bot_instance()

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '', 200

@app.route('/set_webhook', methods=['GET', 'POST'])
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + '/' + BOT_TOKEN)
    return "Webhook set", 200

@app.route('/remove_webhook', methods=['GET', 'POST'])
def remove_webhook():
    bot.remove_webhook()
    return "Webhook removed", 200

if __name__ == '__main__':
    print(1234)
    # Проверяем, установлен ли вебхук
    webhook_info = bot.get_webhook_info()
    if webhook_info.url:
        print(f"Бот работает через вебхук: {webhook_info.url}")
        app.run(debug=DEBUG, port=PORT)
    else:
        print("Вебхук не установлен. Запуск бота в режиме long polling.")
        # bot.remove_webhook()
        bot.polling( none_stop=True)
        print(12345)
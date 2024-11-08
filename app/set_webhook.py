import requests

from bot import bot
from config import WEBHOOK_URL, SECRET_TOKEN, BOT_TOKEN, SSL_CERT


def set_webhook():
    # url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    # data = {
    #     'url': WEBHOOK_URL + SECRET_TOKEN,
    #     # Указываем, какие типы обновлений мы хотим получать
    #     'allowed_updates': ['message', 'callback_query', 'inline_query']
    # }
    #
    # response = requests.post(url, json=data)
    # print(f"Status Code: {response.status_code}")
    # print(f"Response: {response.json()}")
    bot.remove_webhook()
    webhook_info = bot.set_webhook(
        url=WEBHOOK_URL + SECRET_TOKEN,
        certificate=open(SSL_CERT, 'rb')
    )
    print('WebHook Info: ',webhook_info)


if __name__ == "__main__":
    set_webhook()

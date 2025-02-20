import logging
import ssl
from flask import Flask, request, abort, jsonify
from telebot import types, custom_filters
from telebot.storage import StateRedisStorage

from database import pool_stats, db_pool
from shedule import  init_scheduler, create_scheduler_endpoints
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

init_scheduler(app)

create_scheduler_endpoints(app)



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


@app.route('/pool/status')
def pool_status():
    """Текущий статус пула"""
    try:
        return jsonify({
            'status': 'active',
            'min_connections': db_pool.minconn,
            'max_connections': db_pool.maxconn,
            'used_connections': len(db_pool._used),
            'free_connections': len(db_pool._pool),
            'total_requests': pool_stats.total_requests,
            'failed_requests': pool_stats.failed_requests,
            'last_error': pool_stats.last_error,
            'last_error_time': pool_stats.last_error_time
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/pool/history')
def pool_history():
    """История использования пула"""
    return jsonify(pool_stats.connection_history)


@app.route('/pool/connections/active')
def active_connections():
    """Информация об активных соединениях"""
    active_conns = []
    for conn in db_pool._used:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT pid, backend_start, query_start, state_change, state FROM pg_stat_activity WHERE pid = pg_backend_pid()")
                conn_info = cursor.fetchone()
                if conn_info:
                    active_conns.append({
                        'pid': conn_info[0],
                        'backend_start': conn_info[1].isoformat() if conn_info[1] else None,
                        'query_start': conn_info[2].isoformat() if conn_info[2] else None,
                        'state_change': conn_info[3].isoformat() if conn_info[3] else None,
                        'state': conn_info[4]
                    })
        except Exception as e:
            active_conns.append({'error': str(e)})

    return jsonify(active_conns)


@app.route('/pool/'+SECRET_TOKEN+'/health')
def pool_health():
    """Проверка здоровья пула"""
    health_status = {
        'is_healthy': True,
        'issues': []
    }

    # Проверяем использование пула
    used_ratio = len(db_pool._used) / db_pool.maxconn
    if used_ratio > 0.8:
        health_status['is_healthy'] = False
        health_status['issues'].append(f'High pool usage: {used_ratio * 100:.1f}%')

    # Проверяем ошибки
    if pool_stats.failed_requests > 0:
        error_ratio = pool_stats.failed_requests / pool_stats.total_requests
        if error_ratio > 0.1:  # Более 10% ошибок
            health_status['is_healthy'] = False
            health_status['issues'].append(f'High error rate: {error_ratio * 100:.1f}%')

    return jsonify(health_status)


@app.route('/pool/'+SECRET_TOKEN+'/reset')
def reset_stats():
    """Сброс статистики"""
    with pool_stats.stats_lock:
        pool_stats.total_requests = 0
        pool_stats.failed_requests = 0
        pool_stats.last_error = None
        pool_stats.last_error_time = None
        pool_stats.connection_history = []
    return jsonify({'message': 'Stats reset successfully'})


# Добавим простой HTML интерфейс
@app.route('/pool/'+SECRET_TOKEN)
def index():
    return """
    <html>
        <head>
            <title>DB Pool Monitor</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .card { border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 5px; }
                .error { color: red; }
                .success { color: green; }
            </style>
            <script>
                function updateStats() {
                    fetch('/pool/status')
                        .then(response => response.json())
                        .then(data => {
                            document.getElementById('poolStatus').innerHTML = 
                                `<h3>Pool Status</h3>
                                 <p>Used Connections: ${data.used_connections}</p>
                                 <p>Free Connections: ${data.free_connections}</p>
                                 <p>Total Requests: ${data.total_requests}</p>
                                 <p>Failed Requests: ${data.failed_requests}</p>
                                 ${data.last_error ? `<p class="error">Last Error: ${data.last_error}</p>` : ''}`;
                        });
                }

                // Обновляем каждые 5 секунд
                setInterval(updateStats, 5000);
                updateStats();
            </script>
        </head>
        <body>
            <h1>Database Pool Monitor</h1>
            <div id="poolStatus" class="card"></div>
            <div class="card">
                <h3>Actions</h3>
                <button onclick="fetch('/pool/reset')">Reset Stats</button>
            </div>
        </body>
    </html> """




if __name__ == '__main__':
    # Инициализация
    logger.info('Starting bot initialization...')



    # Проверяем, установлен ли вебхук
    webhook_info = bot.get_webhook_info()
    logger.info('Checking webhook info...')

    if webhook_info.url or not DEBUG:
        logger.info(f"Bot is running in webhook mode: {webhook_info.url}")
        if SSL_CERT and SSL_PRIV:
            app.run(
                host=SERVER_HOST,
                port=SERVER_PORT,
                debug=True
                )
        else:
            app.run(
                host=SERVER_HOST,
                port=SERVER_PORT,
                ssl_context=(SSL_CERT, SSL_PRIV),
                debug=False
            )
    else:
        logger.info("No webhook set. Starting bot in polling mode...")
        app.run(
            host=SERVER_HOST,
            port=SERVER_PORT,
            debug=False
        )
        bot.polling(none_stop=True)
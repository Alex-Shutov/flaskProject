import logging
from datetime import datetime

import pytz
import schedule
import time
import threading

from flask_apscheduler import APScheduler

from app_types import OrderTypeRu
from bot import bot
from config import CHANNEL_CHAT_ID
from database import get_connection


def generate_daily_report():
    """Генерирует и отправляет ежедневный отчет о продажах"""
    try:
        today = datetime.now().date()

        # Получаем заказы за сегодня
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Запрос для прямых продаж
                direct_query = """
                                   WITH order_counts AS (
                                       SELECT 
                                           o.id,
                                           o.total_price,
                                           o.manager_id,
                                           u.name as manager_name,
                                           u.username as manager_username,
                                           COUNT(CASE WHEN oi.is_main_product THEN 1 END) as main_products,
                                           COUNT(CASE WHEN NOT oi.is_main_product THEN 1 END) as additional_products
                                       FROM orders o
                                       LEFT JOIN users u ON o.manager_id = u.id
                                       LEFT JOIN order_items oi ON o.id = oi.order_id
                                       WHERE o.order_type = 'direct' 
                                       AND o.status = 'closed'
                                       AND DATE(o.closed_date) = %s
                                       GROUP BY o.id, o.total_price, o.manager_id, u.name, u.username
                                       ORDER BY o.id
                                   )
                                   SELECT *, 
                                          SUM(main_products) OVER() as total_main,
                                          SUM(additional_products) OVER() as total_additional
                                   FROM order_counts
                               """
                cursor.execute(direct_query, (today,))
                direct_sales = cursor.fetchall()

                # Запрос для Авито
                avito_query = """
                                   WITH order_counts AS (
                                       SELECT 
                                           o.id,
                                           o.total_price,
                                           o.manager_id,
                                           u.name as manager_name,
                                           u.username as manager_username,
                                           c.name as courier_name,
                                           c.username as courier_username,
                                           array_agg(DISTINCT ap.tracking_number) as tracking_numbers,
                                           o.status,
                                           COUNT(CASE WHEN oi.is_main_product THEN 1 END) as main_products,
                                           COUNT(CASE WHEN NOT oi.is_main_product THEN 1 END) as additional_products
                                       FROM orders o
                                       LEFT JOIN users u ON o.manager_id = u.id
                                       LEFT JOIN users c ON o.courier_id = c.id
                                       LEFT JOIN avito_photos ap ON o.id = ap.order_id
                                       LEFT JOIN order_items oi ON o.id = oi.order_id
                                       WHERE o.order_type = 'avito'
                                       AND DATE(o.created_at) = %s
                                       GROUP BY o.id, o.total_price, o.manager_id, u.name, u.username, 
                                               c.name, c.username, o.status
                                       ORDER BY o.id
                                   )
                                   SELECT *, 
                                          SUM(main_products) OVER() as total_main,
                                          SUM(additional_products) OVER() as total_additional
                                   FROM order_counts
                               """
                cursor.execute(avito_query, (today,))
                avito_sales = cursor.fetchall()

                # Запрос для доставок
                delivery_query = """
                                   WITH order_counts AS (
                                       SELECT 
                                           o.id,
                                           o.total_price,
                                           o.manager_id,
                                           u.name as manager_name,
                                           u.username as manager_username,
                                           c.name as courier_name,
                                           c.username as courier_username,
                                           o.delivery_address,
                                           o.status,
                                           COUNT(CASE WHEN oi.is_main_product THEN 1 END) as main_products,
                                           COUNT(CASE WHEN NOT oi.is_main_product THEN 1 END) as additional_products
                                       FROM orders o
                                       LEFT JOIN users u ON o.manager_id = u.id
                                       LEFT JOIN users c ON o.courier_id = c.id
                                       LEFT JOIN order_items oi ON o.id = oi.order_id
                                       WHERE o.order_type = 'delivery'
                                       AND o.status IN ('closed')
                                       AND DATE(o.closed_date) = %s
                                       GROUP BY o.id, o.total_price, o.manager_id, u.name, u.username,
                                               c.name, c.username, o.delivery_address, o.status
                                       ORDER BY o.id
                                   )
                                   SELECT *, 
                                          SUM(main_products) OVER() as total_main,
                                          SUM(additional_products) OVER() as total_additional
                                   FROM order_counts
                               """
                cursor.execute(delivery_query, (today,))
                delivery_sales = cursor.fetchall()

        # Формируем отчет
        report = [
            f"📊 Отчет за {today.strftime('%d.%m.%Y')}\n",
            "\n💼 Продажи в шоуруме:"
        ]

        total_direct = 0
        if direct_sales:
            for sale in direct_sales:
                total_direct += sale[1]
                report.append(
                    f"• Заказ #{str(sale[0]).zfill(4)}ㅤ\n"
                    f"  👤 Менеджер: {sale[4]}"
                )
            total_main = direct_sales[0][-2] or 0  # Предпоследний столбец
            total_additional = direct_sales[0][-1] or 0  # Последний столбец
            report.append(f"\nПродали основных продуктов: {total_main}\n")
            report.append(f"Продали допников: {total_additional}\n")
        else:
            report.append("Нет продаж")


        report.append("\n📬 Продажи Авито:")
        total_avito = 0
        if avito_sales:
            for sale in avito_sales:
                total_avito += sale[1]
                track_numbers = ', '.join(sale[5]) if sale[5] else 'нет трек-номеров'
                report.append(
                    f"• Заказ #{str(sale[0]).zfill(4)}ㅤ\n"
                    f"  👤 Менеджер: {sale[4]}\n"
                     f" 🚚 Курьер: {sale[6]}\n"
                    f"  📊 Статус: {OrderTypeRu[sale[8].upper()].value}\n"
                )
            total_main = avito_sales[0][-2] or 0
            total_additional = avito_sales[0][-1] or 0
            report.append(f"\nПродали основных продуктов: {total_main}\n")
            report.append(f"Продали допников: {total_additional}\n")
        else:
            report.append("Нет продаж")

        report.append("\n🚚 Доставка:")
        total_delivery = 0
        if delivery_sales:
            for sale in delivery_sales:
                total_delivery += sale[1]
                status = "📊 Доставлен" if sale[8] == 'closed' else "⚡️ Частично доставлен"
                report.append(
                    f"• Заказ #{str(sale[0]).zfill(4)}ㅤ\n{status}\n"
                    f"  👤 Менеджер: {sale[4]}\n"
                    f"  🚚 Курьер: {sale[6]}\n"
                )
            total_main = delivery_sales[0][-2] or 0
            total_additional = delivery_sales[0][-1] or 0
            report.append(f"\nПродали основных продуктов: {total_main}\n")
            report.append(f"Продали допников: {total_additional}\n")
        else:
            report.append("Нет доставок")

        report.append(f"Все молодцы! Все солнышки☀️")

        # Отправляем отчет в канал
        bot.send_message(
            CHANNEL_CHAT_ID,
            '\n'.join(report),
            parse_mode='HTML'
        )

    except Exception as e:
        print(f"Error generating daily report: {e}")


logger = logging.getLogger(__name__)

# Создаем экземпляр планировщика
scheduler = APScheduler()


def init_scheduler(app):
    """Инициализация планировщика"""
    try:
        # Конфигурация планировщика
        app.config['SCHEDULER_API_ENABLED'] = True
        app.config['SCHEDULER_TIMEZONE'] = "Asia/Yekaterinburg"

        # Инициализация
        scheduler.init_app(app)

        # Добавляем задачу
        scheduler.add_job(
            id='daily_report',
            func=generate_daily_report,  # Ваша оригинальная функция
            trigger='cron',
            hour=0,
            minute=0
        )

        # Запускаем планировщик
        scheduler.start()
        logger.info("Scheduler initialized successfully")

    except Exception as e:
        logger.error(f"Error initializing scheduler: {e}")
        raise


def test_scheduler():
    """Функция для тестирования планировщика"""
    try:
        generate_daily_report()
        return True
    except Exception as e:
        logger.error(f"Test scheduler error: {e}")
        return False


# Эндпоинт для ручного запуска отчета (опционально)
def create_scheduler_endpoints(app):
    @app.route('/trigger-report', methods=['POST'])
    def trigger_report():
        try:
            generate_daily_report()
            return 'Report generated successfully', 200
        except Exception as e:
            logger.error(f"Error triggering report: {e}")
            return str(e), 500

    @app.route('/scheduler-status', methods=['GET'])
    def scheduler_status():
        try:
            jobs = scheduler.get_jobs()
            return {
                'status': 'running',
                'jobs': [
                    {
                        'id': job.id,
                        'next_run': job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
                    } for job in jobs
                ]
            }
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
            return {'status': 'error', 'message': str(e)}, 500
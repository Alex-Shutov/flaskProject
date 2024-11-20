import json
from telebot import types
from bot import bot
from telebot.states.sync.context import StateContext
from database import get_connection
from states import AdminStates


@bot.message_handler(commands=['pack_info'])
def handle_pack_info_command(message: types.Message, state: StateContext):
    """Обработчик команды /pack_info"""
    # Создаем CRUD клавиатуру
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Добавить", callback_data="packing_rule-add"),
        types.InlineKeyboardButton("Посмотреть", callback_data="packing_rule-view"),
        types.InlineKeyboardButton("Редактировать", callback_data="packing_rule-edit"),
        types.InlineKeyboardButton("Удалить", callback_data="packing_rule-delete")
    )

    bot.reply_to(message, "Управление правилами упаковки:", reply_markup=markup)
    state.set(AdminStates.manage_packing_rules)


@bot.callback_query_handler(func=lambda call: call.data.endswith('-view') and call.data.startswith('packing_rule'))
def handle_view_packing_rules(call: types.CallbackQuery, state: StateContext):
    """Просмотр правил упаковки"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                # Получаем все активные правила упаковки
                cursor.execute("""
                    SELECT 
                        name,
                        description,
                        conditions,
                        priority,
                        is_active,
                        created_at
                    FROM packing_rules
                    WHERE is_active = true
                    ORDER BY priority DESC
                """)
                rules = cursor.fetchall()

                if not rules:
                    bot.edit_message_text(
                        "Активных правил упаковки не найдено.",
                        call.message.chat.id,
                        call.message.message_id
                    )
                    return

                # Формируем сообщение с информацией о правилах
                message_parts = ["📦 Активные правила упаковки:\n"]

                for rule in rules:
                    name, description, conditions, priority, is_active, created_at = rule

                    # Форматируем условия для читаемости
                    formatted_conditions = format_packing_conditions(conditions)

                    rule_info = (
                        f"\n🔷 {name}\n"
                        f"📝 Описание: {description}\n"
                        f"⚙️ Условия:\n{formatted_conditions}\n"
                        f"📊 Приоритет: {priority}\n"
                        f"📅 Создано: {created_at.strftime('%d.%m.%Y %H:%M')}\n"
                        f"{'✅ Активно' if is_active else '❌ Неактивно'}\n"
                        f"{'─' * 30}"
                    )
                    message_parts.append(rule_info)

                # Разбиваем сообщение на части, если оно слишком длинное
                message_text = '\n'.join(message_parts)
                if len(message_text) > 4096:
                    for i in range(0, len(message_text), 4096):
                        if i == 0:
                            bot.edit_message_text(
                                message_text[i:i + 4096],
                                call.message.chat.id,
                                call.message.message_id
                            )
                        else:
                            bot.send_message(
                                call.message.chat.id,
                                message_text[i:i + 4096]
                            )
                else:
                    bot.edit_message_text(
                        message_text,
                        call.message.chat.id,
                        call.message.message_id
                    )

    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка при получении правил: {str(e)}")
        print(f"Error in handle_view_packing_rules: {e}")


def format_packing_conditions(conditions):
    """Форматирует условия упаковки для читаемого отображения"""
    try:
        if isinstance(conditions, str):
            conditions = json.loads(conditions)

        formatted_parts = []

        # Форматируем страну происхождения
        if 'origin' in conditions:
            formatted_parts.append(f"📍 Страна: {conditions['origin']}")

        # Форматируем количество товаров
        if 'item_count' in conditions:
            if isinstance(conditions['item_count'], dict):
                if 'type' in conditions['item_count']:
                    if conditions['item_count']['type'] == 'even':
                        formatted_parts.append("📦 Количество: четное")
                if 'min' in conditions['item_count']:
                    formatted_parts.append(f"📦 Минимальное количество: {conditions['item_count']['min']}")
            else:
                formatted_parts.append(f"📦 Количество: {conditions['item_count']}")

        # Форматируем требование одинаковых параметров
        if 'same_params' in conditions:
            formatted_parts.append(
                "🔄 Параметры: должны быть одинаковыми" if conditions['same_params']
                else "🔄 Параметры: могут различаться"
            )

        # Форматируем требование упаковки
        if 'needs_packing' in conditions:
            formatted_parts.append(
                "📦 Требует упаковки" if conditions['needs_packing']
                else "📦 Не требует упаковки"
            )

        return "\n".join(f"  {part}" for part in formatted_parts)
    except Exception as e:
        print(f"Error formatting conditions: {e}")
        return str(conditions)
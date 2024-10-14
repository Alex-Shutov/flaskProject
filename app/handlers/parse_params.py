import re
from telebot import types

# Идентифицирует тип параметра
def identify_param_type(param):
    print(param)
    print('param')
    if param.startswith('+') and param.endswith('+'):
        return 'number'
    elif '(' in param and ')' in param:
        return 'enum'
    else:
        return 'string'

# Валидация числовых значений
def validate_number(value):
    try:
        float(value)  # Проверка на возможность приведения к числу
        return True
    except ValueError:
        return False

# Парсинг перечислений
def parse_enum_options(param):
    options = param[param.index('(')+1:param.index(')')].split(',')
    return [opt.strip() for opt in options]

# Создание Inline клавиатуры для перечислений
def create_enum_keyboard(options):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(opt, callback_data=opt) for opt in options]
    keyboard.add(*buttons)
    return keyboard

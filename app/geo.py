import json
import psycopg2
from config import DATABASE_CONFIG, DELIVERY_ZONES


def get_zone_info_by_color(color_hex: str) -> dict:
    """Получает информацию о зоне по её hex-цвету"""
    color_mapping = {
        '#56db40': {'name': 'Зеленая', 'color': 'green', 'prices': DELIVERY_ZONES['green']},
        '#ffd21e': {'name': 'Желтая', 'color': 'yellow', 'prices': DELIVERY_ZONES['yellow']},
        '#ed4543': {'name': 'Красная', 'color': 'red', 'prices': DELIVERY_ZONES['red']},
        '#b51eff': {'name': 'Фиолетовая', 'color': 'purple', 'prices': DELIVERY_ZONES['purple']}
    }
    return color_mapping.get(color_hex.lower())


def add_white_zone(cursor):
    """Добавляет или обновляет белую зону"""
    # Проверяем существование белой зоны
    cursor.execute("SELECT id FROM delivery_zones WHERE color = 'white'")
    white_zone_exists = cursor.fetchone()

    if white_zone_exists:
        # Обновляем существующую белую зону
        cursor.execute("""
            UPDATE delivery_zones 
            SET name = 'Белая',
                base_price = %s,
                additional_item_price = %s,
                polygon = NULL
            WHERE id = %s
        """, (
            DELIVERY_ZONES['white']['base_price'],
            DELIVERY_ZONES['white']['additional_price'],
            white_zone_exists[0]
        ))
    else:
        # Создаем новую белую зону
        cursor.execute("""
            INSERT INTO delivery_zones 
                (name, color, base_price, additional_item_price, polygon)
            VALUES 
                ('Белая', 'white', %s, %s, NULL)
        """, (
            DELIVERY_ZONES['white']['base_price'],
            DELIVERY_ZONES['white']['additional_price']
        ))


def import_delivery_zones(geojson_path: str):
    """Импортирует зоны доставки из GeoJSON файла"""
    # Читаем GeoJSON файл
    with open(geojson_path, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)

    connection = psycopg2.connect(**DATABASE_CONFIG)
    try:
        with connection.cursor() as cursor:
            # Проверяем, есть ли данные в связанных таблицах
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM courier_trips WHERE zone_id IS NOT NULL
                ) OR EXISTS (
                    SELECT 1 FROM delivery_addresses WHERE zone_id IS NOT NULL
                );
            """)
            has_dependent_data = cursor.fetchone()[0]

            if has_dependent_data:
                print("Найдены связанные данные в таблицах courier_trips и/или delivery_addresses.")
                print("Обновляем существующие зоны вместо полной очистки...")

                # Получаем существующие зоны
                cursor.execute("SELECT id, name FROM delivery_zones")
                existing_zones = {name: zone_id for zone_id, name in cursor.fetchall()}

            else:
                # Если нет связанных данных, можно использовать TRUNCATE CASCADE
                cursor.execute("TRUNCATE TABLE delivery_zones CASCADE")
                existing_zones = {}

            # Обрабатываем каждую зону
            for feature in geojson_data['features']:
                fill_color = feature['properties']['fill']
                zone_info = get_zone_info_by_color(fill_color)

                if not zone_info:
                    print(f"Пропускаем зону с неизвестным цветом: {fill_color}")
                    continue

                # Получаем координаты полигона
                coordinates = feature['geometry']['coordinates'][0]
                polygon_points = [f"{lon} {lat}" for lon, lat in coordinates]
                polygon_wkt = f"POLYGON(({', '.join(polygon_points)}))"

                if zone_info['name'] in existing_zones:
                    # Обновляем существующую зону
                    cursor.execute("""
                        UPDATE delivery_zones 
                        SET color = %s,
                            base_price = %s,
                            additional_item_price = %s,
                            polygon = ST_GeomFromText(%s, 4326)
                        WHERE id = %s
                    """, (
                        zone_info['color'],
                        zone_info['prices']['base_price'],
                        zone_info['prices']['additional_price'],
                        polygon_wkt,
                        existing_zones[zone_info['name']]
                    ))
                else:
                    # Создаем новую зону
                    cursor.execute("""
                        INSERT INTO delivery_zones 
                            (name, color, base_price, additional_item_price, polygon)
                        VALUES 
                            (%s, %s, %s, %s, ST_GeomFromText(%s, 4326))
                    """, (
                        zone_info['name'],
                        zone_info['color'],
                        zone_info['prices']['base_price'],
                        zone_info['prices']['additional_price'],
                        polygon_wkt
                    ))

            # Добавляем или обновляем белую зону
            add_white_zone(cursor)

            connection.commit()
            print("Зоны доставки успешно обновлены!")

            # Проверяем результат
            cursor.execute("""
                SELECT name, color, base_price, additional_item_price 
                FROM delivery_zones 
                ORDER BY 
                    CASE 
                        WHEN color = 'white' THEN 2 
                        ELSE 1 
                    END,
                    name;
            """)
            zones = cursor.fetchall()
            print("\nАктивные зоны доставки:")
            for name, color, base_price, additional_price in zones:
                print(f"- {name} ({color}):")
                print(f"  Базовая цена: {base_price}")
                print(f"  Доп. товар: {additional_price}")

    except Exception as e:
        connection.rollback()
        print(f"Ошибка при импорте зон: {e}")
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    import_delivery_zones('Map GeoJson.geojson')
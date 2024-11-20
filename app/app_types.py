from enum import Enum

class UserRole(Enum):
    MANAGER = 'Manager'
    COURIER = 'Courier'
    ADMIN = 'Admin'
    OWNER = 'Owner'

class SaleType(Enum):
    DIRECT='direct'
    DELIVERY='delivery'
    AVITO='avito'

class SaleTypeRu(Enum):
    DIRECT='Прямая'
    DELIVERY='Доставка'
    AVITO='Авито'

class OrderType(Enum):
    ACTIVE='active'
    IN_DELIVERY='in_delivery'
    IN_PACKING='in_packing'
    READY_TO_DELIVERY='ready_to_delivery'
    PARTLY_DELIVERED = 'partly_delivered'
    CLOSED='closed'
    REFUND='refund'

class OrderTypeRu(Enum):
    ACTIVE = 'Активный'
    IN_DELIVERY = 'В доставке'
    IN_PACKING='На упаковке'
    READY_TO_DELIVERY='Готов к доставке'
    PARTLY_DELIVERED = 'Частично доставлен'
    CLOSED = 'Закрыт'
    REFUND = 'Возврат'

class TripStatus(Enum):
    CREATED = 'created'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'

class TripStatusRu(Enum):
    CREATED = 'Создана'
    IN_PROGRESS = 'В процессе'
    COMPLETED = 'Завершена'
    CANCELLED = 'Отменена'
class TrackNumberStatus(Enum):
    PENDING = 'pending'
    IN_PACKING = 'in_packing'
    CLOSED = 'closed'
    SKIPPED = 'skipped'
    REPACKED = 'repacked'
class TrackNumberStatusRu(Enum):
    PENDING = 'Не обработан'
    IN_PACKING = 'В процессе'
    CLOSED = 'Закрыт'
    SKIPPED = 'Пропущен'
    REPACKED='Переупакован'




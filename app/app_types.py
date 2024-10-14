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
    CLOSED='closed'
    REFUND='refund'

class OrderTypeRu(Enum):
    ACTIVE = 'Активный'
    IN_DELIVERY = 'В доставке'
    IN_PACKING='На упаковке'
    READY_TO_DELIVERY='Готов к доставке'
    CLOSED = 'Закрыт'
    REFUND = 'Возврат'


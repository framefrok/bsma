# users.py
import sqlite3
import logging
from typing import Optional, Tuple

import database

logger = logging.getLogger(__name__)


def ensure_user(user_id: int, username: Optional[str] = None) -> None:
    """
    Проверяет, есть ли пользователь в БД, если нет — создаёт запись.
    """
    try:
        database.ensure_user(user_id, username)
    except Exception:
        logger.exception(f"Ошибка при ensure_user {user_id}")


def set_user_bonus(user_id: int, bonus: float) -> None:
    """
    Устанавливает бонус пользователя, например 0.2 для +20% к цене покупки.
    """
    try:
        ensure_user(user_id)
        database.update_user_bonus(user_id, float(bonus))
    except Exception:
        logger.exception(f"Ошибка при set_user_bonus {user_id}")


def get_user_bonus(user_id: int) -> float:
    """
    Возвращает бонус пользователя в виде float.
    """
    try:
        ensure_user(user_id)
        user = database.get_user(user_id)
        return float(user.get('bonus', 0.0)) if user else 0.0
    except Exception:
        logger.exception(f"Ошибка при get_user_bonus {user_id}")
        return 0.0


def adjust_prices_for_user(user_id: Optional[int], base_buy: float, base_sell: float) -> Tuple[float, float]:
    """
    Корректирует базовые цены для пользователя с учётом его бонуса.
    Обычно используется для отображения пользователю.
    """
    try:
        bonus = get_user_bonus(user_id) if user_id is not None else 0.0
        adj_buy = base_buy / (1 + bonus) if bonus else base_buy
        adj_sell = base_sell / (1 + bonus) if bonus else base_sell
        return float(round(adj_buy, 6)), float(round(adj_sell, 6))
    except Exception:
        logger.exception(f"Ошибка при adjust_prices_for_user {user_id}")
        return base_buy, base_sell


def set_user_notify(user_id: int, enabled: bool) -> None:
    """
    Включает или отключает уведомления для пользователя.
    """
    try:
        ensure_user(user_id)
        database.update_user_push_settings(user_id, enabled=enabled)
    except Exception:
        logger.exception(f"Ошибка при set_user_notify {user_id}")


def set_user_notify_interval(user_id: int, interval_minutes: int) -> None:
    """
    Устанавливает интервал уведомлений для пользователя в минутах.
    """
    try:
        ensure_user(user_id)
        database.update_user_push_settings(user_id, interval=interval_minutes)
    except Exception:
        logger.exception(f"Ошибка при set_user_notify_interval {user_id}")


def get_user_notify_settings(user_id: int) -> Tuple[bool, int]:
    """
    Возвращает кортеж: (уведомления включены?, интервал в минутах)
    """
    try:
        ensure_user(user_id)
        settings = database.get_user_push_settings(user_id)
        return settings['enabled'], settings['interval']
    except Exception:
        logger.exception(f"Ошибка при get_user_notify_settings {user_id}")
        return True, 15


def set_user_last_reminder(user_id: int, timestamp: int) -> None:
    """
    Записывает время последнего уведомления для пользователя.
    """
    try:
        ensure_user(user_id)
        database.set_user_last_reminder(user_id, timestamp)
    except Exception:
        logger.exception(f"Ошибка при set_user_last_reminder {user_id}")


def get_users_with_notifications_enabled() -> list[dict]:
    """
    Возвращает список словарей пользователей, у которых включены уведомления.
    """
    try:
        return database.get_users_with_notifications_enabled()
    except Exception:
        logger.exception("Ошибка при get_users_with_notifications_enabled")
        return []

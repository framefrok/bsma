# market.py
import re
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import database
import users

logger = logging.getLogger(__name__)

EMOJI_TO_RESOURCE = {
    "🪵": "Дерево",
    "🪨": "Камень",
    "🍞": "Провизия",
    "🐴": "Лошади"
}

RESOURCE_EMOJI = {v: k for k, v in EMOJI_TO_RESOURCE.items()}


def _parse_market_message_lines(text: str) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Парсит текст рынка и возвращает словарь:
    { "Дерево": {"buy": float, "sell": float, "quantity": int}, ... }
    Если ни одного ресурса не найдено — возвращает None.
    """
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    resources: Dict[str, Dict[str, float]] = {}
    current_resource = None
    current_quantity = 0

    # Паттерны
    resource_pattern = re.compile(r"^(.+?):\s*([\d, ]+)\s*([🪵🪨🍞🐴])\s*$")
    price_pattern = re.compile(r"(?:[📈📉]?\s*)?Купить/продать[:\s]*([0-9]+(?:[.,][0-9]+))\s*/\s*([0-9]+(?:[.,][0-9]+))")
    # Альтернативный паттерн, если формат "Купить: 8.31 Продать: 6.80"
    alt_price_pattern = re.compile(r"Купить[:\s]*([0-9]+(?:[.,][0-9]+))[,;\s]+Продать[:\s]*([0-9]+(?:[.,][0-9]+))")

    for line in lines:
        # Пропускаем заголовки
        if line.startswith("🎪") or line.lower().startswith("рынок"):
            continue

        # Resource line
        m = resource_pattern.match(line)
        if m:
            name_part = m.group(1).strip()
            qty_str = m.group(2).replace(' ', '').replace(',', '')
            emoji = m.group(3)
            try:
                qty = int(qty_str) if qty_str.isdigit() else 0
            except Exception:
                qty = 0
            current_quantity = qty
            # Map emoji to standard resource name; fallback to parsed name
            resource_name = EMOJI_TO_RESOURCE.get(emoji, name_part)
            current_resource = resource_name
            # ensure placeholder
            resources[current_resource] = {"buy": 0.0, "sell": 0.0, "quantity": current_quantity}
            continue

        # Price line
        pm = price_pattern.search(line) or alt_price_pattern.search(line)
        if pm and current_resource:
            buy_raw = pm.group(1).replace(',', '.')
            sell_raw = pm.group(2).replace(',', '.')
            try:
                buy_price = float(buy_raw)
                sell_price = float(sell_raw)
            except Exception:
                continue
            resources[current_resource] = {
                "buy": buy_price,
                "sell": sell_price,
                "quantity": current_quantity
            }
            current_resource = None
            current_quantity = 0
            continue

        # Иногда ресурс и цены могут быть в одной строк: "Дерево: 96 342 449 🪵 Купить/продать: 8.31/6.80💰"
        combined_match = re.search(r"^(.+?):\s*([\d, ]+)\s*([🪵🪨🍞🐴])\s+.*Купить/продать[:\s]*([0-9]+(?:[.,][0-9]+))\s*/\s*([0-9]+(?:[.,][0-9]+))", line)
        if combined_match:
            name_part = combined_match.group(1).strip()
            qty_str = combined_match.group(2).replace(' ', '').replace(',', '')
            emoji = combined_match.group(3)
            buy_raw = combined_match.group(4).replace(',', '.')
            sell_raw = combined_match.group(5).replace(',', '.')
            try:
                qty = int(qty_str) if qty_str.isdigit() else 0
            except Exception:
                qty = 0
            resource_name = EMOJI_TO_RESOURCE.get(emoji, name_part)
            try:
                buy_price = float(buy_raw)
                sell_price = float(sell_raw)
            except Exception:
                continue
            resources[resource_name] = {"buy": buy_price, "sell": sell_price, "quantity": qty}
            current_resource = None
            current_quantity = 0
            continue

    if not resources:
        return None
    return resources


def parse_market_message(text: str, sender_id: Optional[int] = None) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Парсит сообщение рынка. Если sender_id указан и у отправителя включены бонусы,
    преобразует присланные (скорее всего скорректированные) цены обратно в базовые
    (то есть нормализует к "без-бонусов"), чтобы база хранила единый эталон.
    Возвращает словарь: {resource: {"buy": base_buy, "sell": base_sell, "quantity": qty}, ...}
    """
    parsed = _parse_market_message_lines(text)
    if not parsed:
        return None

    # Если нет sender_id — просто возвращаем найденное как "базовые" (предполагаем, что отправитель без бонусов)
    if sender_id is None:
        return parsed

    try:
        bonus = users.get_user_bonus(sender_id)  # float, например 0.2 для 20%
    except Exception:
        bonus = 0.0

    normalized: Dict[str, Dict[str, float]] = {}
    for resource, vals in parsed.items():
        buy = vals.get("buy", 0.0)
        sell = vals.get("sell", 0.0)
        qty = int(vals.get("quantity", 0) or 0)

        # Inverse of adjust_prices_for_user used elsewhere:
        # adjusted_buy = base_buy / (1 + bonus)
        # adjusted_sell = base_sell * (1 + bonus)
        # So to recover base:
        try:
            base_buy = buy * (1 + bonus) if bonus else buy
        except Exception:
            base_buy = buy
        try:
            base_sell = sell / (1 + bonus) if bonus else sell
        except Exception:
            base_sell = sell

        normalized[resource] = {"buy": float(round(base_buy, 6)), "sell": float(round(base_sell, 6)), "quantity": qty}

    return normalized


def handle_market_forward(bot, message) -> None:
    """
    Обрабатывает пересланное сообщение рынка: парсит, нормализует цены (учитывая бонус отправителя),
    сохраняет в БД и уведомляет отправителя о результате.
    """
    try:
        # Проверка, что это пересылка (forward)
        sender_id = None
        forward_from = getattr(message, "forward_from", None)
        forward_sender_name = getattr(message, "forward_sender_name", None)
        if forward_from and getattr(forward_from, "id", None):
            sender_id = forward_from.id
        elif forward_sender_name:
            sender_id = None
        else:
            # Не пересылка — игнорируем
            bot.reply_to(message, "❌ Сообщение должно быть пересылкой (forward) от бота рынка.")
            return

        # Проверка времени (не старше 1 часа)
        now_ts = int(time.time())
        msg_ts = int(getattr(message, "date", now_ts))
        if now_ts - msg_ts > 3600:
            bot.reply_to(message, "❌ Сообщение слишком старое (более 1 часа). Отправьте свежий форвард.")
            return

        parsed = parse_market_message(message.text or "", sender_id=sender_id)
        if not parsed:
            bot.reply_to(message, "❌ Не удалось распознать данные рынка. Проверьте формат сообщения.")
            return

        saved = 0
        for resource, vals in parsed.items():
            buy = float(vals.get("buy", 0.0))
            sell = float(vals.get("sell", 0.0))
            qty = int(vals.get("quantity", 0) or 0)
            timestamp = int(msg_ts)
            try:
                database.insert_market_record(resource, buy, sell, qty, timestamp)
                saved += 1
            except Exception as e:
                logger.exception(f"Ошибка сохранения записи рынка для {resource}: {e}")

        # Запись в history
        try:
            conn = database.get_connection()
            cur = conn.cursor()
            summary = f"Получен форвард рынка: сохранено {saved} записей (отправитель: {forward_from.username if forward_from and getattr(forward_from, 'username', None) else forward_sender_name or 'unknown'})"
            cur.execute("INSERT INTO history (timestamp, text) VALUES (?, ?)", (int(time.time()), summary))
            conn.commit()
            conn.close()
        except Exception:
            logger.debug("Не удалось записать историю форварда", exc_info=True)

        if saved > 0:
            bot.reply_to(message, f"✅ Сохранено {saved} записей рынка.")
        else:
            bot.reply_to(message, "ℹ️ Записей для сохранения не найдено.")

    except Exception as e:
        logger.exception("Ошибка в handle_market_forward")
        try:
            bot.reply_to(message, "❌ Произошла внутренняя ошибка при обработке форварда.")
        except Exception:
            pass


def calculate_speed(records: List[dict], price_field: str = "buy") -> Optional[float]:
    if not records or len(records) < 2:
        return None
    prev = records[-2]
    last = records[-1]
    price_delta = last[price_field] - first[price_field]
    time_delta_minutes = (last['timestamp'] - first['timestamp']) / 60.0
    if time_delta_minutes < 0.1:
        return None
    speed = price_delta / time_delta_minutes
    return round(speed, 6)


def get_trend(records: List[dict], price_field: str = "buy") -> str:
    if not records or len(records) < 2:
        return "stable"
    prev_price = records[-2][price_field]
    last_price = records[-1][price_field]
    if last_price > first_price:
        return "up"
    elif last_price < first_price:
        return "down"
    else:
        return "stable"


def _calculate_speed_from_records(records: List[dict], price_field: str = "buy") -> Optional[float]:
    if not records or len(records) < 2:
        return None
    prev = records[-2]
    last = records[-1]
    try:
        t_delta = (last['timestamp'] - first['timestamp']) / 60.0
        if t_delta <= 0:
            return None
        price_delta = last[price_field] - first[price_field]
        speed = price_delta / t_delta
        return float(speed)
    except Exception:
        return None


def compute_extrapolated_price(resource: str, user_id: Optional[int] = None, lookback_minutes: int = 60) -> Tuple[Optional[float], Optional[float], str, Optional[float], Optional[int]]:
    """
    Возвращает:
      (predicted_buy, predicted_sell, trend, adjusted_speed, last_timestamp)
    Все цены возвращаются уже скорректированными под user_id (если указан) — то есть для отображения пользователю.
    """
    try:
        latest = database.get_latest_market(resource)
        if not latest:
            return None, None, "stable", None, None

        recent = database.get_recent_market(resource, minutes=lookback_minutes)
        if not recent:
            recent = [latest]

        # raw base prices are stored in DB
        last_ts = int(latest['timestamp'])
        last_buy_raw = float(latest['buy'])
        last_sell_raw = float(latest['sell'])

        # compute raw speeds
        speed_buy_raw = _calculate_speed_from_records(recent, "buy")
        speed_sell_raw = _calculate_speed_from_records(recent, "sell")

        trend = get_trend(recent, "buy")

        # get user bonus and get adjusted last prices
        try:
            bonus = users.get_user_bonus(user_id) if user_id is not None else 0.0
        except Exception:
            bonus = 0.0

        # Adjust last (base) -> for user
        try:
            adj_last_buy, adj_last_sell = users.adjust_prices_for_user(user_id, last_buy_raw, last_sell_raw)
        except Exception:
            # fallback naive
            if bonus:
                adj_last_buy = last_buy_raw / (1 + bonus)
                adj_last_sell = last_sell_raw * (1 + bonus)
            else:
                adj_last_buy = last_buy_raw
                adj_last_sell = last_sell_raw

        # Adjust speed for user (speed should be scaled same way as price seen by user)
        adj_speed_buy = None
        if speed_buy_raw is not None:
            try:
                adj_speed_buy = speed_buy_raw / (1 + bonus)
            except Exception:
                adj_speed_buy = speed_buy_raw

        # Extrapolate forward from last record to now
        now_ts = int(time.time())
        elapsed_minutes = max(0.0, (now_ts - last_ts) / 60.0)

        pred_buy = adj_last_buy
        pred_sell = adj_last_sell
        if adj_speed_buy is not None and abs(adj_speed_buy) > 1e-12 and elapsed_minutes > 0:
            pred_buy = adj_last_buy + adj_speed_buy * elapsed_minutes

        # For sell side we try a similar approach if possible
        adj_speed_sell = None
        if speed_sell_raw is not None:
            try:
                adj_speed_sell = speed_sell_raw * (1 + bonus)  # selling speed scales opposite in some conventions; use conservative approach
            except Exception:
                adj_speed_sell = speed_sell_raw
        if adj_speed_sell is not None and elapsed_minutes > 0:
            try:
                pred_sell = adj_last_sell + adj_speed_sell * elapsed_minutes
            except Exception:
                pred_sell = adj_last_sell

        # round results
        try:
            pred_buy = float(round(pred_buy, 6))
        except Exception:
            pred_buy = None
        try:
            pred_sell = float(round(pred_sell, 6))
        except Exception:
            pred_sell = None

        return pred_buy, pred_sell, trend, (adj_speed_buy if adj_speed_buy is not None else None), last_ts

    except Exception:
        logger.exception("Ошибка в compute_extrapolated_price")
        return None, None, "stable", None, None

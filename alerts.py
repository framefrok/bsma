
# alerts.py
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from telebot import types
import database
import users
import market

logger = logging.getLogger(__name__)


def calculate_speed(records: List[dict], price_field: str = "buy") -> Optional[float]:
    if not records or len(records) < 2:
        return None
    first = records[0]
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
    first_price = records[0][price_field]
    last_price = records[-1][price_field]
    if last_price > first_price:
        return "up"
    elif last_price < first_price:
        return "down"
    else:
        return "stable"


def schedule_alert(alert_id: int, bot):
    try:
        alert = database.get_alert_by_id(alert_id)
        if not alert:
            return

        alert_time = datetime.fromisoformat(alert['alert_time'])
        now = datetime.now()
        sleep_s = (alert_time - now).total_seconds()
        if sleep_s > 0:
            time.sleep(sleep_s)

        current = database.get_latest_market(alert['resource'])
        if not current:
            try:
                bot.send_message(alert['user_id'], f"⚠️ Невозможно проверить цель: нет данных по {alert['resource']}.")
            except Exception:
                pass
            database.update_alert_status(alert_id, 'error')
            return

        current_price_adj, _ = users.adjust_prices_for_user(alert['user_id'], current['buy'], current['sell'])

        reached = False
        if alert['direction'] == 'down' and current_price_adj <= alert['target_price']:
            reached = True
        if alert['direction'] == 'up' and current_price_adj >= alert['target_price']:
            reached = True

        if reached:
            try:
                bot.send_message(alert['user_id'], f"🔔 **Таймер сработал!** 🎯\n{alert['resource']} достигла {alert['target_price']:.2f}💰\nТекущая: {current_price_adj:.2f}💰")
            except Exception:
                pass
            database.update_alert_status(alert_id, 'completed')
            if alert.get('chat_id') and alert['chat_id'] != alert['user_id']:
                try:
                    group_users = database.get_group_users(alert['chat_id'])
                    mentions = ' '.join([f"@{u['username']}" for u in group_users if u['username']])
                    alert_msg = f"🔔 **Таймер @{alert['user_id']} сработал!**\n{alert['resource']} достигла {alert['target_price']:.2f}💰 (текущая: {current_price_adj:.2f}💰)\n{mentions}" if mentions else f"🔔 Таймер сработал: {alert['resource']} {alert['target_price']:.2f}💰"
                    bot.send_message(alert['chat_id'], alert_msg, parse_mode='Markdown')
                except Exception:
                    bot.send_message(alert['chat_id'], f"🔔 Таймер сработал: {alert['resource']} {alert['target_price']:.2f}💰")
        else:
            try:
                bot.send_message(alert['user_id'], f"⏰ **Таймер истёк**\nЦель ({alert['target_price']:.2f}💰) не достигнута. Текущая: {current_price_adj:.2f}💰")
            except Exception:
                pass
            database.update_alert_status(alert_id, 'expired')

    except Exception as e:
        logger.exception("Ошибка в schedule_alert")
        try:
            database.update_alert_status(alert_id, 'error')
        except Exception:
            pass


def update_dynamic_timers_once(bot):
    try:
        active_alerts = database.get_active_alerts()
        now = datetime.now()
        for alert in active_alerts:
            try:
                records = database.get_recent_market(alert['resource'], minutes=15)
                if not records or len(records) < 2:
                    continue

                latest = database.get_latest_market(alert['resource'])
                if not latest:
                    continue

                created_ts = datetime.fromisoformat(alert['created_at']).timestamp() if alert.get('created_at') else 0
                if latest['timestamp'] <= created_ts:
                    continue

                bonus = users.get_user_bonus(alert['user_id'])
                current_adj_price, _ = users.adjust_prices_for_user(alert['user_id'], latest['buy'], latest['sell'])
                speed_raw = calculate_speed(records, "buy")
                if speed_raw is None:
                    continue

                adj_speed = speed_raw / (1 + bonus) if isinstance(bonus, float) else speed_raw
                if adj_speed is None or adj_speed == 0:
                    continue

                current_trend = get_trend(records, "buy")
                if (alert['direction'] == "down" and current_trend == "up") or (alert['direction'] == "up" and current_trend == "down"):
                    try:
                        bot.send_message(alert['user_id'], f"⚠️ **Тренд изменился** 📊\n{alert['resource']}: теперь {current_trend}. Алерты деактивирован.")
                    except Exception:
                        pass
                    database.update_alert_status(alert['id'], 'trend_changed')
                    continue

                # Fixed logic: direction based on target vs current at creation, but update if already reached
                if (alert['direction'] == "down" and current_adj_price <= alert['target_price']) or (alert['direction'] == "up" and current_adj_price >= alert['target_price']):
                    try:
                        bot.send_message(alert['user_id'], f"🔔 **Цель достигнута!** 🎯\n{alert['resource']}: {alert['target_price']:.2f}💰 (текущая: {current_adj_price:.2f}💰)")
                    except Exception:
                        pass
                    database.update_alert_status(alert['id'], 'completed')
                    continue

                # Only update if speed in correct direction
                price_diff = abs(alert['target_price'] - current_adj_price)
                if price_diff == 0:
                    continue
                expected_speed_dir = -1 if alert['direction'] == "down" else 1
                if (adj_speed * expected_speed_dir) <= 0:
                    continue  # Wrong direction

                time_minutes = price_diff / abs(adj_speed)
                new_alert_time = datetime.now() + timedelta(minutes=time_minutes)

                database.update_alert_fields(alert['id'], {
                    'alert_time': new_alert_time.isoformat(),
                    'speed': adj_speed,
                    'current_price': current_adj_price
                })

                try:
                    old = datetime.fromisoformat(alert['alert_time']) if alert.get('alert_time') else None
                    if old:
                        diff_min = abs((new_alert_time - old).total_seconds() / 60.0)
                        if diff_min > 5:
                            bot.send_message(alert['user_id'], f"🔄 **Таймер обновлён** ⏱️\n{alert['resource']}: новое время {new_alert_time.strftime('%H:%M:%S')}")
                except Exception:
                    pass

            except Exception as e:
                logger.exception(f"Ошибка при обновлении алерта {alert.get('id')}: {e}")
    except Exception as e:
        logger.exception("Ошибка в update_dynamic_timers_once")


def cleanup_expired_alerts_loop():
    while True:
        try:
            now = datetime.now()
            active = database.get_active_alerts()
            expired_ids = []
            for a in active:
                try:
                    if not a.get('alert_time'):
                        continue
                    at = datetime.fromisoformat(a['alert_time'])
                    if at < (now - timedelta(hours=1)):
                        expired_ids.append(a['id'])
                except Exception:
                    continue
            for aid in expired_ids:
                database.update_alert_status(aid, 'cleanup_expired')
                logger.info(f"Очистка: деактивирован алерт {aid} (просрочен)")
        except Exception as e:
            logger.exception("Ошибка в cleanup_expired_alerts_loop")
        time.sleep(600)


def stale_db_reminder_loop(bot):
    while True:
        try:
            global_ts = database.get_global_latest_timestamp()
            now_ts = int(time.time())
            delta = None if not global_ts else now_ts - global_ts
            if delta is not None and delta < 15 * 60:
                time.sleep(60)
                continue

            users_list = database.get_users_with_notifications_enabled()
            for u in users_list:
                uid = u["id"]
                interval = int(u.get("notify_interval", 15))
                last = int(u.get("last_reminder", 0))
                if now_ts - last >= interval * 60:
                    try:
                        bot.send_message(uid, "⚠️ **БД устарела!** 📉\nДанные не обновлялись >15 мин. Пришлите форвард рынка 🎪.\n/push — настройки.")
                    except Exception:
                        pass
                    database.set_user_last_reminder(uid, now_ts)

            chats = database.get_chats_with_notifications_enabled()
            for c in chats:
                chat_id = c["chat_id"]
                interval = int(c.get("notify_interval", 15))
                last = int(c.get("last_reminder", 0))
                if now_ts - last >= interval * 60:
                    try:
                        bot.send_message(chat_id, "⚠️ **БД устарела!** 📉\nДанные не обновлялись >15 мин. Пришлите форвард рынка.")
                    except Exception:
                        pass
                    database.set_chat_last_reminder(chat_id, now_ts)

        except Exception:
            logger.exception("Ошибка в stale_db_reminder_loop")
        time.sleep(60)  # Check every minute, send if interval passed


def update_dynamic_timers_loop(bot):
    while True:
        try:
            update_dynamic_timers_once(bot)
        except Exception:
            logger.exception("Ошибка в update_dynamic_timers_loop")
        time.sleep(60)


def check_profit_alerts(bot):
    while True:
        try:
            chats = database.get_chats_with_profit_alerts()
            for chat in chats:
                chat_id = chat['chat_id']
                alerts_list = database.get_chat_profit_alerts(chat_id)
                latest = database.get_latest_market_all()
                for alert in alerts_list:
                    resource = alert['resource']
                    threshold = alert['threshold_price']
                    min_qty = alert['min_quantity']
                    current = next((r for r in latest if r['resource'] == resource), None)
                    if current and current['buy'] <= threshold and current['quantity'] >= min_qty:
                        try:
                            group_users = database.get_group_users(chat_id)
                            mentions = ' '.join([f"@{u['username']}" for u in group_users if u['username']])
                            alert_msg = f"🛒 **Время покупать!** 📉\n{resource}: {current['buy']:.2f}💰 (≥{min_qty:,} шт.)\n{mentions}"
                            bot.send_message(chat_id, alert_msg, parse_mode='Markdown')
                            database.deactivate_profit_alert(chat_id, resource)
                        except Exception:
                            pass
        except Exception as e:
            logger.exception("Ошибка в check_profit_alerts")
        time.sleep(300)


def start_background_tasks(bot):
    threading.Thread(target=cleanup_expired_alerts_loop, daemon=True).start()
    threading.Thread(target=update_dynamic_timers_loop, args=(bot,), daemon=True).start()
    threading.Thread(target=stale_db_reminder_loop, args=(bot,), daemon=True).start()
    threading.Thread(target=check_profit_alerts, args=(bot,), daemon=True).start()


def cmd_timer_handler(bot, message):
    try:
        parts = message.text.split()[1:]
        if len(parts) != 2:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("📉 Падение (down)", callback_data="timer_down"))
            markup.add(types.InlineKeyboardButton("📈 Рост (up)", callback_data="timer_up"))
            res = parts[0].capitalize() if parts else ""
            target = parts[1] if len(parts)>1 else ""
            bot.reply_to(message, f"🔔 **Установить таймер** ⏱️\n/timer {res} {target}\nВыберите направление:", parse_mode='Markdown', reply_markup=markup)
            return

        resource = parts[0].capitalize()
        try:
            target_price = float(parts[1].replace(',', '.'))
            if target_price <= 0:
                bot.reply_to(message, "❌ Цена > 0.")
                return
        except ValueError:
            bot.reply_to(message, "❌ Неверная цена. Пример: 8.50")
            return

        latest = database.get_latest_market(resource)
        if not latest:
            bot.reply_to(message, f"⚠️ Нет данных по {resource}. Пришлите 🎪.")
            return

        records = database.get_recent_market(resource, minutes=15)
        if len(records) < 2:
            bot.reply_to(message, f"⚠️ Недостаточно данных для {resource}.")
            return

        current_raw_buy = latest['buy']
        user_id = message.from_user.id
        current_buy_adj, _ = users.adjust_prices_for_user(user_id, current_raw_buy, latest['sell'])
        bonus = users.get_user_bonus(user_id)
        # Fixed: direction based on target vs current
        if target_price < current_buy_adj:
            direction = "down"
        else:
            direction = "up"

        speed_raw = calculate_speed(records, "buy")
        if speed_raw is None:
            bot.reply_to(message, "⚠️ Не удалось рассчитать скорость.")
            return

        adj_speed = speed_raw / (1 + bonus) if isinstance(bonus, float) else speed_raw
        if adj_speed == 0:
            bot.reply_to(message, "⚠️ Скорость слишком мала.")
            return

        # Fixed check: ensure target in logical direction
        if direction == "down" and target_price >= current_buy_adj:
            bot.reply_to(message, f"⚠️ Для падения цель должна быть ниже текущей ({current_buy_adj:.2f}💰).")
            return
        if direction == "up" and target_price <= current_buy_adj:
            bot.reply_to(message, f"⚠️ Для роста цель должна быть выше текущей ({current_buy_adj:.2f}💰).")
            return

        trend = get_trend(records, "buy")
        if (direction == "down" and trend == "up") or (direction == "up" and trend == "down"):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="timer_cancel"))
            markup.add(types.InlineKeyboardButton("✅ Установить", callback_data="timer_confirm"))
            bot.reply_to(message, f"⚠️ **Предупреждение**\nНаправление противоречит тренду ({trend}). Продолжить?", reply_markup=markup, parse_mode='Markdown')
            return  # Wait for confirm, but for simplicity, proceed with warning

        if (direction == "down" and adj_speed >= 0) or (direction == "up" and adj_speed <= 0):
            bot.reply_to(message, "⚠️ Цена движется не в нужную сторону. Алерты не установлен.")
            return

        price_diff = abs(target_price - current_buy_adj)
        time_minutes = price_diff / abs(adj_speed)
        alert_time = datetime.now() + timedelta(minutes=time_minutes)

        chat_id = message.chat.id if message.chat.type in ['group', 'supergroup'] else None

        alert_id = database.insert_alert_record(user_id, resource, target_price, direction, adj_speed, current_buy_adj, alert_time.isoformat(), chat_id)

        alert_time_str = alert_time.strftime("%H:%M:%S")
        username = message.from_user.username or str(message.from_user.id)
        dir_str = "📉 падение" if direction == 'down' else "📈 рост"
        notify = f"✅ **Таймер установлен!** ⏱️\n"
        notify += f"👤 @{username}\n"
        notify += f"📦 {resource}\n"
        notify += f"💹 Текущая: {current_buy_adj:.2f}💰\n"
        notify += f"🎯 Цель: {target_price:.2f}💰 ({dir_str})\n"
        notify += f"⚡ Скорость: {adj_speed:+.6f}/мин\n"
        notify += f"⏳ ~{int(time_minutes)} мин\n"
        notify += f"🕐 {alert_time_str}"
        sent = bot.reply_to(message, notify, parse_mode='Markdown')

        if chat_id and chat_id != user_id:
            try:
                bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
                database.upsert_chat_settings(chat_id, True, database.get_chat_settings(chat_id)["notify_interval"], pinned_message_id=sent.message_id)
            except Exception:
                pass

        threading.Thread(target=schedule_alert, args=(alert_id, bot), daemon=True).start()

    except Exception:
        logger.exception("Ошибка в cmd_timer_handler")
        bot.reply_to(message, "❌ Ошибка установки таймера.")


def cmd_status_handler(bot, message):
    user_id = message.from_user.id
    alerts_list = database.get_user_active_alerts(user_id)
    if not alerts_list:
        bot.reply_to(message, "📋 **Нет активных алертов** 🔔\nИспользуйте /timer для установки.")
        return
    reply = "📋 **Активные таймеры** ⏱️\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for a in alerts_list:
        time_left = datetime.fromisoformat(a['alert_time']) - datetime.now()
        if time_left.total_seconds() > 0:
            left_min = int(time_left.total_seconds() // 60)
            left_sec = int(time_left.total_seconds() % 60)
            left_str = f"{left_min} мин {left_sec} сек"
            time_str = datetime.fromisoformat(a['alert_time']).strftime("%H:%M:%S")
            dir_str = "📉 падение" if a['direction']=='down' else "📈 рост"
            reply += f"• **{a['resource']}** → {a['target_price']:.2f}💰 ({dir_str})\n"
            reply += f"  ⏳ {left_str} | 🕐 {time_str}\n\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗑️ Отменить все", callback_data="cancel_all"))
    bot.reply_to(message, reply, parse_mode='Markdown', reply_markup=markup)


def cmd_cancel_handler(bot, message):
    user_id = message.from_user.id
    count = database.cancel_user_alerts(user_id)
    bot.reply_to(message, f"🗑️ **Удалено {count} алертов** 📋")


def cmd_help_handler(bot, message):
    help_text = """
🆘 **BS Market Analytics - Полная справка** 🤖

📊 **Статистика & Анализ:**
• /stat - Текущие цены, тренды, прогнозы (с бонусом)
• /history [ресурс] - История цен за 24ч (Дерево, Камень, Провизия, Лошади)

🔔 **Алерты & Таймеры:**
• /timer <ресурс> <цена> - Таймер на цену (up/down)
• /status - Активные алерты
• /cancel - Отменить все
• /buyalert <ресурс> <макс_цена> <мин_кол> - Групповой алерт покупки

📈 **Торговля & Статистика:**
• /top_player - Ваши сделки, выгода (24ч)
• /top_list - Топ-10 по прибыли
• Перешлите "Ты купил/продал" для фиксации

⚙️ **Настройки:**
• /settings - Бонусы (якорь, уровень)
• /push - Уведомления, интервалы
• /clearbuyalerts - Очистить групповые алерты

🎪 **Обновление:** Перешлите сообщение рынка для свежих данных.

Для групп: Авто-упоминания активных игроков, закрепление алертов.
Поддержка: @your_support
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="menu_stat"))
    markup.add(types.InlineKeyboardButton("🔔 Таймеры", callback_data="menu_alerts"))
    markup.add(types.InlineKeyboardButton("🏆 Топ", callback_data="menu_top"))
    markup.add(types.InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings"))
    bot.reply_to(message, help_text, parse_mode='Markdown', reply_markup=markup)

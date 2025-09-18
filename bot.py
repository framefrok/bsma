# bot.py 

import logging
import telebot
from telebot import types
import database
import users
import alerts
import market
import time
import re
from datetime import datetime

TOKEN = "YOUR_BOT_TOKEN_HERE"
bot = telebot.TeleBot(TOKEN)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

alerts.start_background_tasks(bot)

#Команда /start

@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    users.ensure_user(user_id, username)
    if message.chat.type in ['group', 'supergroup']:
        database.ensure_group_user(message.chat.id, user_id, username)
    welcome = f"🎉 Привет, @{username}! Добро пожаловать в BS Market Analytics!\n\n📋 Доступные команды:\n/stat — Статистика рынка\n/history [ресурс] — История цен\n/status — Алерты\n/cancel — Отмена алертов\n/settings — Бонусы\n/push — Уведомления\n/top_player — Ваша статистика\n/top_list — Топ игроков\n/help — Полная справка"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="menu_stat"))
    markup.add(types.InlineKeyboardButton("🔔 Алерты", callback_data="menu_alerts"))
    markup.add(types.InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings"))
    bot.reply_to(message, welcome, reply_markup=markup)

#Команда /help

@bot.message_handler(commands=['help'])
def cmd_help(message):
    alerts.cmd_help_handler(bot, message)

#Команда /stat

@bot.message_handler(commands=['stat'])
def cmd_stat(message):
    user_id = message.from_user.id
    bonus_pct = int(users.get_user_bonus(user_id) * 100)
    now = datetime.now()
    global_ts = database.get_global_latest_timestamp()
    update_str = datetime.fromtimestamp(global_ts).strftime("%d.%m.%Y %H:%M") if global_ts else "❌ Нет данных"

    resources = ['Дерево', 'Камень', 'Провизия', 'Лошади']
    reply = f"📊 **Текущая статистика рынка** 🏪\n🕐 Обновлено: {update_str}\n💎 Ваш бонус: +{bonus_pct}%\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    week_start = int(time.time()) - 7*24*3600

    for res in resources:
        pred_buy, pred_sell, trend, speed, last_ts = market.compute_extrapolated_price(res, user_id)
        if pred_buy is None:
            reply += f"{market.RESOURCE_EMOJI.get(res, '❓')} **{res}**: Нет данных\n\n"
            continue
        last_update_str = datetime.fromtimestamp(last_ts).strftime("%H:%M") if last_ts else "N/A"
        was_buy = database.get_market_week_max_price(res, 'buy', week_start)
        was_sell = database.get_market_week_max_price(res, 'sell', week_start)
        was_buy_adj, was_sell_adj = users.adjust_prices_for_user(user_id, was_buy, was_sell)
        buy_range = database.get_market_week_range(res, 'buy', week_start)
        sell_range = database.get_market_week_range(res, 'sell', week_start)
        max_qty = database.get_market_week_max_qty(res, week_start)
        trend_emoji = "📈" if trend == "up" else "📉" if trend == "down" else "➖"
        speed_str = f"{speed:+.4f}/мин" if speed else "стабильно"
        reply += f"{market.RESOURCE_EMOJI.get(res, '')} **{res}**\n"
        reply += f"  🕒 Обновление: {last_update_str}\n"
        reply += f"  💹 Покупка: {pred_buy:>7.3f}💰 (макс.нед: {was_buy_adj:.3f})\n"
        reply += f"     Диапазон: {buy_range[0]:.3f} — {buy_range[1]:.3f}\n"
        reply += f"  💰 Продажа: {pred_sell:>7.3f}💰 (макс.нед: {was_sell_adj:.3f})\n"
        reply += f"     Диапазон: {sell_range[0]:.3f} — {sell_range[1]:.3f}\n"
        reply += f"  📦 Макс. объём: {max_qty:,}\n"
        reply += f"  📊 Тренд: {trend_emoji} {speed_str}\n\n"

    reply += "━━━━━━━━━━━━━━━━━━━━━━━\n📈 Рост | 📉 Падение | ➖ Стабильно\n*Цены с вашим бонусом*"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="refresh_stat"))
    bot.reply_to(message, reply, parse_mode='Markdown', reply_markup=markup)

#Команда /history

@bot.message_handler(commands=['history'])
def cmd_history(message):
    parts = message.text.split()
    resource = parts[1].capitalize() if len(parts) > 1 else None
    if not resource or resource not in ['Дерево', 'Камень', 'Провизия', 'Лошади']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        btns = [types.InlineKeyboardButton(res, callback_data=f"hist_{res.lower()}") for res in ['Дерево', 'Камень', 'Провизия', 'Лошади']]
        markup.add(*btns)
        bot.reply_to(message, "📜 Выберите ресурс для истории:", reply_markup=markup)
        return
    records = database.get_market_history(resource, hours=24)
    if not records:
        bot.reply_to(message, f"❌ Нет истории для {resource}.")
        return
    reply = f"📜 **История {resource} (24ч)** 📊\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    grouped = {}
    for r in records:
        dt = datetime.fromtimestamp(r['timestamp'])
        hour = dt.hour
        if hour not in grouped:
            grouped[hour] = []
        grouped[hour].append(r)
    for hour in sorted(grouped, reverse=True):
        reply += f"🕐 **{hour:02d}:00**:\n"
        for rec in sorted(grouped[hour], key=lambda x: x['timestamp']):
            time_str = datetime.fromtimestamp(rec['timestamp']).strftime("%H:%M")
            buy_adj, sell_adj = users.adjust_prices_for_user(message.from_user.id, rec['buy'], rec['sell'])
            reply += f"  {time_str} | Купить: {buy_adj:.2f}💰 | Продать: {sell_adj:.2f}💰\n"
        reply += "\n"
    trend = market.get_trend(records, "buy")
    speed = alerts.calculate_speed(records, "buy")
    trend_str = f"**Тренд:** {'📉 Падает' if trend=='down' else '📈 Растёт' if trend=='up' else '➖ Стабилен'} ({speed:+.4f}/мин)" if speed else "**Тренд:** ➖ Стабилен"
    reply += trend_str
    bot.reply_to(message, reply, parse_mode='Markdown')

#Команда /status

@bot.message_handler(commands=['status'])
def cmd_status(message):
    alerts.cmd_status_handler(bot, message)

#Команда /cancel

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    alerts.cmd_cancel_handler(bot, message)

#Команда /settings

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    anchor = bool(user.get('anchor', 0))
    trade_level = user.get('trade_level', 0)
    bonus = (0.02 if anchor else 0) + (0.02 * trade_level)
    users.set_user_bonus(user_id, bonus)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("⚓ Якорь: " + ("✅" if anchor else "❌"), callback_data="settings_anchor"))
    markup.add(types.InlineKeyboardButton(f"📈 Уровень: {trade_level}", callback_data="settings_trade"))
    reply = f"⚙️ **Настройки бонусов** 💎\n• ⚓ Якорь: {'✅ Вкл (+2%)' if anchor else '❌ Выкл'}\n• 📈 Уровень торговли: {trade_level} (+{trade_level*2}%)\n• 💎 Итоговый бонус: **{bonus*100:.0f}%**"
    bot.reply_to(message, reply, parse_mode='Markdown', reply_markup=markup)



@bot.callback_query_handler(func=lambda call: call.data.startswith("settings_"))
def callback_settings(call):
    user_id = call.from_user.id
    if call.data == "settings_anchor":
        current = database.get_user(user_id).get('anchor', 0)
        new = 1 - current
        database.update_user_field(user_id, 'anchor', new)
        bonus = users.get_user_bonus(user_id)
        bot.answer_callback_query(call.id, f"⚓ Якорь {'включен ✅' if new else 'выключен ❌'} (бонус: {bonus*100:.0f}%)")
        bot.edit_message_text(f"⚙️ Настройки обновлены! Бонус: {bonus*100:.0f}%", call.message.chat.id, call.message.message_id)
    elif call.data == "settings_trade":
        msg = bot.send_message(call.message.chat.id, "📈 Отправьте новый уровень торговли (число 0-10):")
        bot.register_next_step_handler(msg, set_trade_level)

def set_trade_level(message):
    try:
        level = int(message.text)
        if level < 0 or level > 50:
            raise ValueError
        database.update_user_field(message.from_user.id, 'trade_level', level)
        bonus = users.get_user_bonus(message.from_user.id)
        bot.reply_to(message, f"✅ Уровень торговли: {level} (бонус: {bonus*100:.0f}%)")
    except ValueError:
        bot.reply_to(message, "❌ Неверное число (0-10). Попробуйте снова.")

@bot.message_handler(commands=['push'])
def cmd_push(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_group = message.chat.type in ['group', 'supergroup']
    settings = database.get_user_push_settings(user_id) if not is_group else database.get_chat_settings(chat_id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    enabled_text = "✅ Включить" if not settings.get('notify_enabled', True) else "❌ Отключить"
    markup.add(types.InlineKeyboardButton(f"{enabled_text} уведомления", callback_data="push_toggle"))
    markup.add(types.InlineKeyboardButton(f"⏱️ Интервал: {settings.get('notify_interval', 15)} мин", callback_data="push_interval"))
    if is_group:
        markup.add(types.InlineKeyboardButton("📌 Открепить все", callback_data="push_unpin"))
        markup.add(types.InlineKeyboardButton("🚫 Не закреплять", callback_data="push_no_pin"))
    reply = f"⚡ **Настройки уведомлений** 🔔\n• Статус: {'✅ Вкл' if settings.get('notify_enabled', True) else '❌ Выкл'}\n• Интервал: {settings.get('notify_interval', 15)} мин"
    bot.reply_to(message, reply, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("push"))
def callback_push(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    is_group = call.message.chat.type in ['group', 'supergroup']
    settings = database.get_user_push_settings(user_id) if not is_group else database.get_chat_settings(chat_id)
    if call.data == "push_toggle":
        new_status = not settings.get('enabled', True)
        if is_group:
            database.upsert_chat_settings(chat_id, new_status, settings['notify_interval'])
        else:
            database.update_user_push_settings(user_id, enabled=new_status)
        bot.answer_callback_query(call.id, f"🔔 Уведомления {'включены ✅' if new_status else 'отключены ❌'}")
        bot.edit_message_text(f"⚡ Настройки обновлены!\n• Статус: {'✅ Вкл' if new_status else '❌ Выкл'}", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    elif call.data == "push_interval":
        msg = bot.send_message(call.message.chat.id, "⏱️ Отправьте интервал в минутах (5-60):")
        if is_group:
            bot.register_next_step_handler(msg, lambda m: set_chat_interval(m, chat_id))
        else:
            bot.register_next_step_handler(msg, lambda m: set_user_interval(m, user_id))
    elif call.data == "push_unpin":
        database.unpin_all_messages(chat_id)
        bot.answer_callback_query(call.id, "📌 Все сообщения откреплены")
    elif call.data == "push_no_pin":
        database.set_chat_no_pin(chat_id, True)
        bot.answer_callback_query(call.id, "🚫 Закрепление отключено")

def set_user_interval(message, user_id):
    try:
        minutes = int(message.text)
        if minutes < 5 or minutes > 60:
            raise ValueError
        database.update_user_push_settings(user_id, interval=minutes)
        bot.reply_to(message, f"✅ Интервал: {minutes} мин")
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат (5-60 мин)")

def set_chat_interval(message, chat_id):
    try:
        minutes = int(message.text)
        if minutes < 5 or minutes > 60:
            raise ValueError
        settings = database.get_chat_settings(chat_id)
        database.upsert_chat_settings(chat_id, settings['notify_enabled'], minutes)
        bot.reply_to(message, f"✅ Интервал: {minutes} мин")
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат (5-60 мин)")

@bot.message_handler(commands=['timer'])
def cmd_timer(message):
    alerts.cmd_timer_handler(bot, message)

@bot.message_handler(commands=['buyalert'])
def cmd_buyalert(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "❌ Команда только для групп.")
        return

    parts = message.text.split()[1:]
    if len(parts) != 3:
        markup = types.InlineKeyboardMarkup(row_width=2)
        btns = [types.InlineKeyboardButton(res, callback_data=f"balert_{res.lower()}") for res in ['Дерево', 'Камень', 'Провизия', 'Лошади']]
        markup.add(*btns)
        bot.reply_to(message, "📉 **Установить алерт на покупку**\n/buyalert <ресурс> <макс_цена> <мин_кол-во>\nПример: /buyalert Дерево 8.5 50000\n\nВыберите ресурс:", parse_mode='Markdown', reply_markup=markup)
        return

    resource = parts[0].capitalize()
    try:
        threshold = float(parts[1])
        min_qty = int(parts[2])
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат. Цена — число, кол-во — целое.")
        return

    if threshold <= 0 or min_qty <= 0:
        bot.reply_to(message, "❌ Цена и кол-во > 0.")
        return

    chat_id = message.chat.id
    conn = database.get_connection()
    c = conn.cursor()

    # Сначала попробуем обновить
    c.execute("""
        UPDATE chat_profit_alerts
        SET threshold_price = ?, min_quantity = ?, active = 1
        WHERE chat_id = ? AND resource = ?
    """, (threshold, min_qty, chat_id, resource))

    # Если обновлено 0 строк — значит, записи не было, вставляем новую
    if c.rowcount == 0:
        c.execute("""
            INSERT INTO chat_profit_alerts (chat_id, resource, threshold_price, min_quantity, active)
            VALUES (?, ?, ?, ?, 1)
        """, (chat_id, resource, threshold, min_qty))

    conn.commit()
    conn.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗑️ Удалить", callback_data=f"clear_alert_{resource.lower()}"))
    bot.reply_to(message, f"✅ **Алерты обновлён**\n📉 {resource}: ≤{threshold}💰 при ≥{min_qty:,} шт.\n@{message.from_user.username} готов к покупке!", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['clearbuyalerts'])
def cmd_clearbuyalerts(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "❌ Команда только для групп.")
        return
    chat_id = message.chat.id
    database.clear_all_profit_alerts(chat_id)
    bot.reply_to(message, "🗑️ **Все алерты покупки удалены** 📉")

@bot.message_handler(commands=['top_player'])
def cmd_top_player(message):
    user_id = message.from_user.id
    txs = database.get_user_transactions(user_id)
    if not txs:
        bot.reply_to(message, "📊 У вас нет транзакций за день.")
        return
    reply = f"🏆 **Ваша статистика (24ч)** 👤 @{message.from_user.username}\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    total_profit = sum(t['profit'] for t in txs)
    buy_txs = [t for t in txs if t['action'] == 'buy']
    sell_txs = [t for t in txs if t['action'] == 'sell']
    reply += f"💰 Чистая выгода: {total_profit:,.2f}💰\n"
    reply += f"🛒 Покупок: {len(buy_txs)} | 📤 Продаж: {len(sell_txs)}\n\n"
    reply += "**Последние сделки:**\n"
    for t in txs[:5]:
        dt = datetime.fromtimestamp(t['timestamp']).strftime("%H:%M")
        action_emoji = "🛒" if t['action'] == 'buy' else "📤"
        profit_str = f" ({t['profit']:+.2f})"
        reply += f"{action_emoji} {t['resource']}: {t['quantity']:,} по {t['price']:.2f}💰 = {t['total_gold']:.2f}{profit_str} [{dt}]\n"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="refresh_top_player"))
    bot.reply_to(message, reply, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['top_list'])
def cmd_top_list(message):
    profits = database.get_daily_profits()
    user_id = message.from_user.id
    user_rank = database.get_user_rank(user_id)
    reply = f"👑 **Топ игроков по прибыли (24ч)** 🏆\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, p in enumerate(profits, 1):
        user = database.get_user(p['user_id'])
        username = (user.get('username') or f"ID{p['user_id']}") if user else f"ID{p['user_id']}"
        reply += f"{i}. @{username}: {p['net_gold']:,.2f}💰 ({p['tx_count']} сделок)\n"
    reply += f"\n📊 Ваше место: #{user_rank}"
    bot.reply_to(message, reply, parse_mode='Markdown')
    
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    text = message.text or ""
    if "🎪" in text:
        market.handle_market_forward(bot, message)
    elif "Ты купил" in text or "Ты продал" in text:
        handle_transaction(bot, message)

# Парсинг и обработка транзакций

def handle_transaction(bot, message):
    text = message.text or ""
    user_id = message.from_user.id
    timestamp = int(message.date)
    # Parse 
   

    buy_match = re.search(r"Ты купил\s+([\d,]+)\s*([🪵🪨🍞🐴])\s+на сумму\s+([\d,]*\.?\d+)\s*💰", text, re.DOTALL)
    sell_match = re.search(r"Ты продал\s+([\d,]+)\s*([🪵🪨🍞🐴])\s+на сумму\s+([\d,]*\.?\d+)\s*💰", text, re.DOTALL)

    if buy_match:
        qty_str, emoji, total_str = buy_match.groups()
        quantity = int(qty_str.replace(',', ''))
        total_gold = float(total_str.replace(',', ''))
        resource = market.EMOJI_TO_RESOURCE[emoji]
        action = 'buy'
        latest = database.get_latest_market(resource)
        price = total_gold / quantity if quantity > 0 else 0
        profit = -total_gold  # Расход
        database.insert_transaction(user_id, resource, action, quantity, price, total_gold, profit, timestamp)
        profit_str = f" ({profit:+.2f})"
        bot.reply_to(message, f"🛒 **Покупка зафиксирована**\n{resource}: {quantity:,} по {price:.2f}💰 = {total_gold:.2f}💰{profit_str}")
    elif sell_match:
        qty_str, emoji, total_str = sell_match.groups()
        quantity = int(qty_str.replace(',', ''))
        total_gold = float(total_str.replace(',', ''))
        resource = market.EMOJI_TO_RESOURCE[emoji]
        action = 'sell'
        latest = database.get_latest_market(resource)
        price = total_gold / quantity if quantity > 0 else 0
        profit = total_gold  # Выручка
        database.insert_transaction(user_id, resource, action, quantity, price, total_gold, profit, timestamp)
        profit_str = f" (+{profit:.2f} выгода)"
        bot.reply_to(message, f"📤 **Продажа зафиксирована**\n{resource}: {quantity:,} по {price:.2f}💰 = {total_gold:.2f}💰{profit_str}")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('menu_', 'hist_', 'balert_', 'clear_alert_')))
def callback_menu(call):
    if call.data.startswith('menu_stat'):
        cmd_stat(call.message)
    elif call.data.startswith('menu_alerts'):
        cmd_status(call.message)
    elif call.data.startswith('menu_settings'):
        cmd_settings(call.message)
    elif call.data.startswith('hist_'):
        res = call.data.split('_')[1].capitalize()
        cmd_history_for_res(call.message, res)
    elif call.data.startswith('balert_'):
        res = call.data.split('_')[1].capitalize()
        msg = bot.send_message(call.message.chat.id, f"📉 Для {res} отправьте: /buyalert {res} <цена> <кол-во>")
        bot.register_next_step_handler(msg, lambda m: handle_buyalert_step(m, res))
    elif call.data.startswith('clear_alert_'):
        res = call.data.split('_')[2].capitalize()
        database.deactivate_profit_alert(call.message.chat.id, res)
        bot.answer_callback_query(call.id, f"🗑️ Алерты для {res} удалены")

def cmd_history_for_res(message, res):
    # Reuse cmd_history logic
    parts = ['/history', res]
    message.text = ' '.join(parts)
    cmd_history(message)

def handle_buyalert_step(message, res):
    parts = message.text.split()[1:]
    if len(parts) != 2:
        bot.reply_to(message, f"❌ Формат: <цена> <кол-во> для {res}")
        return
    try:
        threshold = float(parts[0])
        min_qty = int(parts[1])
        # Proceed with insert/update as in cmd_buyalert
        chat_id = message.chat.id
        conn = database.get_connection()
        c = conn.cursor()
        c.execute("""
            UPDATE chat_profit_alerts SET threshold_price = ?, min_quantity = ?, active = 1 WHERE chat_id = ? AND resource = ?
        """, (threshold, min_qty, chat_id, res))
        if c.rowcount == 0:
            c.execute("""
                INSERT INTO chat_profit_alerts (chat_id, resource, threshold_price, min_quantity, active) VALUES (?, ?, ?, ?, 1)
            """, (chat_id, res, threshold, min_qty))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ Алерты для {res}: ≤{threshold}💰 при ≥{min_qty:,}")
    except ValueError:
        bot.reply_to(message, "❌ Неверный формат.")

def main():
    logger.info("Бот запущен.")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.exception(f"Ошибка при запуске polling: {e}")

if __name__ == "__main__":
    main()

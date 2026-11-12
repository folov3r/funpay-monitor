"""Common bot commands: /start, /help and the fallback handler."""

from __future__ import annotations

from vkbottle.bot import Bot, Message

from app.bot.keyboards import main_menu_keyboard
from app.bot.texts import HELP_TEXT, WELCOME_TEXT, normalize_text

START_TEXTS = {"/start", "start", "начать", "старт"}
HELP_TEXTS = {"/help", "help", "помощь"}


def register_common_handlers(bot: Bot) -> None:
    @bot.on.message(func=lambda message: normalize_text(message.text) in START_TEXTS)
    async def start_handler(message: Message) -> None:
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer(WELCOME_TEXT, keyboard=main_menu_keyboard())

    @bot.on.message(func=lambda message: normalize_text(message.text) in HELP_TEXTS)
    async def help_handler(message: Message) -> None:
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer(HELP_TEXT, keyboard=main_menu_keyboard())


def register_fallback_handler(bot: Bot) -> None:
    @bot.on.message(state=None)
    async def fallback_handler(message: Message, user_id: int) -> None:
        await message.answer(
            "Не понял сообщение. Пришлите ссылку FunPay или выберите действие кнопкой.\n"
            "Справка: /help",
            keyboard=main_menu_keyboard(),
        )

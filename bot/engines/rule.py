"""Rule mode: numbered menu plus keyword matching, all driven by the Excel."""

from dataclasses import dataclass

from ..knowledge import (
    FaqEntry,
    Knowledge,
    MenuOption,
    Product,
    describe_product,
    list_products,
    render_menu,
)
from ..text import contains_phrase, normalize
from .base import Reply

# Messages that only greet or ask for the menu. Not business data, so they live in code.
GREETINGS = frozenset(
    normalize(word)
    for word in (
        "hola",
        "holi",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "menu",
        "inicio",
        "opciones",
        "pura vida",
    )
)
# Phrases anywhere in a message that ask for the whole catalog. They show the menu,
# whose options list the products by category.
CATALOG_REQUESTS = tuple(
    normalize(phrase) for phrase in ("catalogo", "catálogo", "que venden", "que productos tienen", "que hacen")
)
SUMMARY_QUOTE_LIMIT = 300

Match = MenuOption | FaqEntry | Product


@dataclass(frozen=True)
class _Candidate:
    item: Match
    phrases: tuple[str, ...]


def _candidates(knowledge: Knowledge) -> list[_Candidate]:
    candidates = [_Candidate(option, option.keywords) for option in knowledge.menu]
    candidates += [_Candidate(entry, entry.keywords) for entry in knowledge.faq]
    candidates += [
        _Candidate(product, (normalize(product.name), *product.keywords)) for product in knowledge.products
    ]
    return candidates


def find_match(knowledge: Knowledge, message: str) -> Match | None:
    """Return the item whose longest keyword appears in the message.

    Longer keywords win so "caja musical 30 notas" beats "caja". On a tie, the
    order is menu options, then questions, then products.
    """
    text = normalize(message)
    best: Match | None = None
    best_length = 0
    for candidate in _candidates(knowledge):
        for phrase in candidate.phrases:
            if len(phrase) > best_length and contains_phrase(text, phrase):
                best, best_length = candidate.item, len(phrase)
    return best


def _menu_block(knowledge: Knowledge) -> str:
    menu = render_menu(knowledge)
    return f"{knowledge.message('menu_intro')}\n{menu}" if menu else ""


def _join(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _product_closing(knowledge: Knowledge) -> str:
    option = knowledge.handoff_option()
    return knowledge.message("cierre_producto", opcion_persona=option.number) if option else ""


def _handoff_summary(reason: str, message: str) -> str:
    quoted = message.strip()
    if len(quoted) > SUMMARY_QUOTE_LIMIT:
        quoted = quoted[:SUMMARY_QUOTE_LIMIT].rstrip() + "..."
    return f'{reason} Último mensaje: "{quoted}"'


def _answer_option(knowledge: Knowledge, option: MenuOption, message: str) -> Reply:
    if option.action == "persona":
        return Reply(handoff=True, summary=_handoff_summary(f"Eligió la opción {option.label}.", message))
    if option.action == "productos":
        products = knowledge.products_in(option.category)
        listing = list_products(products) if products else knowledge.message("sin_productos")
        return Reply(text=_join(option.answer, listing, _product_closing(knowledge) if products else ""))
    return Reply(text=option.answer or _menu_block(knowledge))


def _answer(knowledge: Knowledge, item: Match, message: str) -> Reply:
    if isinstance(item, MenuOption):
        return _answer_option(knowledge, item, message)
    if isinstance(item, FaqEntry):
        return Reply(text=item.answer)
    return Reply(text=_join(describe_product(item, knowledge), _product_closing(knowledge)))


def rule_reply(knowledge: Knowledge, message: str, is_new_conversation: bool) -> Reply:
    """Answer a customer message in rule mode."""
    if not knowledge.loaded:
        return Reply(handoff=True, summary=_handoff_summary("El bot no pudo cargar el Excel.", message))

    text = normalize(message)
    option = next((option for option in knowledge.menu if normalize(option.number) == text), None)
    if option is not None:
        return _answer_option(knowledge, option, message)

    item = find_match(knowledge, message)
    if item is not None:
        return _answer(knowledge, item, message)

    if any(contains_phrase(text, phrase) for phrase in CATALOG_REQUESTS):
        menu_block = _menu_block(knowledge)
        if menu_block:
            return Reply(text=menu_block)

    if text in GREETINGS or is_new_conversation:
        return Reply(text=_join(knowledge.message("bienvenida"), _menu_block(knowledge)))

    menu = render_menu(knowledge)
    if not menu:
        return Reply(handoff=True, summary=_handoff_summary("El bot no encontró respuesta.", message))
    return Reply(text=f"{knowledge.message('no_entiendo')}\n{menu}")

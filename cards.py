import discord
from discord import ui

TITLE, BODY, FOOTER, FIELD = 100, 101, 102, 200


def text_parts(message, component_id):
    def visit(nodes):
        for node in nodes:
            if getattr(node, "id", None) == component_id and hasattr(node, "content"):
                yield node.content
            yield from visit(getattr(node, "children", ()))
    return list(visit(message.components))


def footer(message):
    parts = text_parts(message, FOOTER)
    if parts:
        return parts[0].removeprefix("-# ")
    return (message.embeds[0].footer.text or "") if message.embeds else ""


def read_card(message):
    if message.embeds:
        return message.embeds[0]
    title, = text_parts(message, TITLE)
    body = text_parts(message, BODY)
    return discord.Embed(title=title.removeprefix("## "), description=body[0] if body else None)


def layout(card, *, controls=None, banner=None, ping=None):
    view = ui.LayoutView(timeout=None)
    box = ui.Container()
    if banner:
        box.add_item(ui.MediaGallery().add_item(media=f"attachment://{banner}"))
    if ping:
        box.add_item(ui.TextDisplay(ping))
    box.add_item(ui.TextDisplay("## " + card.title, id=TITLE))
    tail = ("-# " + card.footer.text) if card.footer.text else ""
    stamp = f"<t:{int(card.timestamp.timestamp())}:f>" if card.timestamp else ""
    budget = 3990 - len(card.title) - len(tail) - len(stamp) - len(ping or "")
    if card.description:
        body = card.description[:budget]
        box.add_item(ui.TextDisplay(body, id=BODY))
        budget -= len(body)
    for i, field in enumerate(card.fields):
        if budget < 5:
            break
        text = f"**{field.name}**\n{field.value}"[:budget]
        box.add_item(ui.TextDisplay(text, id=FIELD+i))
        budget -= len(text)
    if stamp:
        box.add_item(ui.TextDisplay(stamp))
    if tail:
        box.add_item(ui.TextDisplay(tail, id=FOOTER))
    if controls:
        buttons = list(controls.children)
        controls.clear_items()
        box.add_item(ui.ActionRow(*buttons))
    view.add_item(box)
    return view

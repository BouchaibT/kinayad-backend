# -*- coding: utf-8 -*-
"""
Cartes visuelles Kinayad — design de la landing page, générées à la volée.

Chaque carte est un PNG (800x500) dans la palette maison :
vert forêt #12462b, or #c7923d, crème #f6f2e7, typographie serif.
Envoyées par le bot WhatsApp AVANT le texte chiffré, pour une expérience
patient soignée et professionnelle.

Cartes : bienvenue (1er contact), confirmation de RDV, rappel 24h/2h.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

# Palette Kinayad — identique à la landing page
GREEN_DEEP = (18, 70, 43)
GREEN = (31, 110, 67)
CREAM = (246, 242, 231)
CREAM_2 = (239, 233, 216)
GOLD = (199, 146, 61)
GOLD_SOFT = (230, 197, 132)
WHITE = (255, 253, 247)
INK = (26, 46, 31)
INK_SOFT = (61, 82, 67)
HEADER_SUB = (220, 235, 225)

W, H = 800, 600  # 4:3 — format standard WhatsApp, évite le letterboxing en plein écran
_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"
    return ImageFont.truetype(f"{_FONT_DIR}/{name}", size)


def _fit_font(d: ImageDraw.ImageDraw, text: str, size: int, max_w: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Réduit la taille de police si le texte dépasse la largeur max."""
    f = _font(size, bold)
    while d.textlength(text, font=f) > max_w and size > 14:
        size -= 2
        f = _font(size, bold)
    return f


def _base_card() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 130], fill=GREEN_DEEP)   # bandeau
    d.rectangle([0, 130, W, 134], fill=GOLD)        # filet or
    d.ellipse([W - 160, H - 160, W + 40, H + 40], fill=(238, 222, 190))  # coin décoratif doré discret
    d.text((40, 28), "Kinayad", font=_font(42, True), fill=GOLD_SOFT)
    d.text((42, 88), "Rendez-vous & rappels WhatsApp", font=_font(18), fill=HEADER_SUB)
    return img, d


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Cartes
# ---------------------------------------------------------------------------


def card_welcome_bytes(cabinet_name: str = "Votre cabinet") -> bytes:
    img, d = _base_card()
    # Accueil professionnel de cabinet médical (pas de « Bienvenue ! » générique)
    d.text((40, 185), "Bonjour,", font=_font(34, True), fill=GREEN_DEEP)
    lower = cabinet_name.lower()
    prefix = "vous êtes bien au" if any(
        lower.startswith(w) for w in ("cabinet", "clinique", "centre", "polyclinique", "cabinets")
    ) else "vous êtes bien au cabinet"
    d.text((40, 240), prefix, font=_font(22), fill=INK_SOFT)
    f_name = _fit_font(d, cabinet_name, 30, W - 80, bold=True)
    d.text((40, 280), cabinet_name, font=f_name, fill=GREEN)
    d.text((40, 345), "Réservez votre rendez-vous", font=_font(22), fill=INK_SOFT)
    d.text((40, 380), "en répondant par un chiffre :", font=_font(22), fill=INK_SOFT)
    d.text((40, 435), "1  Prendre RDV        2  Annuler", font=_font(22), fill=INK)
    d.text((40, 470), "3  Horaires              0  Arrêter", font=_font(22), fill=INK)
    d.text((40, H - 38), "100% WhatsApp — simple et accessible à tous", font=_font(17), fill=INK_SOFT)
    return _png_bytes(img)


def card_confirm_bytes(
    cabinet_name: str = "Votre cabinet",
    day: str = "Mardi 01/09/2026",
    time: str = "14:30",
    duration_min: int = 30,
) -> bytes:
    img, d = _base_card()
    d.rounded_rectangle([40, 170, 330, 218], radius=24, fill=GOLD)
    d.text((62, 177), "RDV CONFIRMÉ", font=_font(26, True), fill=GREEN_DEEP)
    d.text((40, 250), "Cabinet", font=_font(20), fill=INK_SOFT)
    f_name = _fit_font(d, cabinet_name, 28, W - 80, bold=True)
    d.text((40, 285), cabinet_name, font=f_name, fill=INK)
    d.text((40, 345), "Date", font=_font(20), fill=INK_SOFT)
    d.text((40, 380), day, font=_font(28, True), fill=INK)
    d.text((40, 440), "Heure", font=_font(20), fill=INK_SOFT)
    d.text((40, 475), f"{time}  ({duration_min} min)", font=_font(28, True), fill=INK)
    d.text((40, H - 46), "Rappels automatiques 24h et 2h avant. À bientôt !", font=_font(17), fill=INK_SOFT)
    return _png_bytes(img)


def card_reminder_bytes(
    cabinet_name: str = "Votre cabinet",
    day: str = "Mardi 01/09/2026",
    time: str = "14:30",
    kind: str = "Rappel 24h",
) -> bytes:
    img, d = _base_card()
    d.rounded_rectangle([40, 170, 300, 218], radius=24, fill=GREEN)
    f_kind = _fit_font(d, kind, 26, 240, bold=True)
    d.text((62, 177), kind, font=f_kind, fill=WHITE)
    d.text((40, 260), "Votre rendez-vous approche :", font=_font(22), fill=INK_SOFT)
    f_name = _fit_font(d, cabinet_name, 30, W - 80, bold=True)
    d.text((40, 305), cabinet_name, font=f_name, fill=GREEN_DEEP)
    d.text((40, 370), f"{day}  à  {time}", font=_font(28, True), fill=INK)
    d.text((40, 435), "Tapez 1 pour confirmer votre présence.", font=_font(20), fill=INK_SOFT)
    d.text((40, 468), "Tapez 2 pour annuler.", font=_font(20), fill=INK_SOFT)
    d.text((40, H - 50), "Un message suffit — merci de répondre", font=_font(17), fill=INK_SOFT)
    return _png_bytes(img)

# -*- coding: utf-8 -*-
"""Prototype v2 des cartes visuelles Kinayad — accents corrigés, positions ajustées."""
from PIL import Image, ImageDraw, ImageFont

GREEN_DEEP = (18, 70, 43)
GREEN = (31, 110, 67)
CREAM = (246, 242, 231)
CREAM_2 = (239, 233, 216)
GOLD = (199, 146, 61)
GOLD_SOFT = (230, 197, 132)
WHITE = (255, 253, 247)
INK = (26, 46, 31)
INK_SOFT = (61, 82, 67)

W, H = 800, 500


def font(size, bold=False):
    name = "DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def base_card():
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 130], fill=GREEN_DEEP)
    d.rectangle([0, 130, W, 134], fill=GOLD)
    d.ellipse([W - 160, H - 160, W + 40, H + 40], fill=CREAM_2)
    d.text((40, 28), "Kinayad", font=font(42, True), fill=GOLD_SOFT)
    d.text((42, 88), "Rendez-vous & rappels WhatsApp", font=font(18), fill=(220, 235, 225))
    return img, d


def line_info(d, label, value, y):
    d.text((40, y), label, font=font(20), fill=INK_SOFT)
    d.text((40, y + 32), value, font=font(28, True), fill=INK)


def card_welcome(name="Cabinet Dr. Hachmi Bouchaib"):
    img, d = base_card()
    d.text((40, 170), "Bienvenue !", font=font(34, True), fill=GREEN_DEEP)
    d.text((40, 222), name, font=font(30, True), fill=GREEN)
    d.text((40, 282), "Réservez votre rendez-vous", font=font(22), fill=INK_SOFT)
    d.text((40, 316), "en répondant par un chiffre :", font=font(22), fill=INK_SOFT)
    d.text((40, 372), "1  Prendre RDV        2  Annuler", font=font(22), fill=INK)
    d.text((40, 410), "3  Horaires              0  Arrêter", font=font(22), fill=INK)
    d.text((40, H - 58), "100% WhatsApp — simple, même sans lire", font=font(17), fill=INK_SOFT)
    return img


def card_confirm(name="Cabinet Dr. Hachmi Bouchaib", day="Mardi 01/09/2026", time="14:30"):
    img, d = base_card()
    d.rounded_rectangle([40, 152, 330, 200], radius=24, fill=GOLD)
    d.text((62, 159), "RDV CONFIRMÉ", font=font(26, True), fill=GREEN_DEEP)
    line_info(d, "Cabinet", name, 218)
    line_info(d, "Date", day, 298)
    line_info(d, "Heure", time + "  (30 min)", 378)
    d.text((40, H - 52), "Rappels automatiques 24h et 2h avant. À bientôt !", font=font(17), fill=INK_SOFT)
    return img


def card_reminder(name="Cabinet Dr. Hachmi Bouchaib", day="Mardi 01/09/2026", time="14:30", kind="Rappel 24h"):
    img, d = base_card()
    d.rounded_rectangle([40, 152, 300, 200], radius=24, fill=GREEN)
    d.text((62, 159), kind, font=font(26, True), fill=WHITE)
    d.text((40, 225), "Votre rendez-vous approche :", font=font(22), fill=INK_SOFT)
    d.text((40, 268), name, font=font(30, True), fill=GREEN_DEEP)
    d.text((40, 330), day + "  à  " + time, font=font(28, True), fill=INK)
    d.text((40, 392), "Tapez 1 pour confirmer votre présence.", font=font(20), fill=INK_SOFT)
    d.text((40, 424), "Tapez 2 pour annuler.", font=font(20), fill=INK_SOFT)
    d.text((40, H - 50), "Un message suffit — merci de répondre", font=font(17), fill=INK_SOFT)
    return img


card_welcome().save("/opt/data/kinayad/preview/card_welcome.png")
card_confirm().save("/opt/data/kinayad/preview/card_confirm.png")
card_reminder().save("/opt/data/kinayad/preview/card_reminder.png")
print("Cartes v2 générées")

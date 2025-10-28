#!/usr/bin/env python3
import os
import io
import json
import logging
import threading
import asyncio
from pathlib import Path
from typing import List
import time

import fitz  # pymupdf
from PIL import Image, ImageOps, ImageFilter
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# --- CONFIG ---
TEMPLATE = "template.png"
COORDS_FILE = "coords.json"
# TOKEN EMBEDDED (as requested)
BOT_TOKEN = "8362681678:AAEwYIX8IgrUAT0zZ8G7EWV8cuUabh8AsQU"
KEEPALIVE = os.getenv("KEEPALIVE", "1")
KEEPALIVE_PORT = int(os.getenv("PORT", "10000"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fayda_bot")

user_sessions = {}  # user_id -> list of pdf paths

def pdf_first_page_as_pil(pdf_path: str, zoom: float = 2.0) -> Image.Image:
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(png_bytes))
        return img.convert("RGBA")
    finally:
        doc.close()

def redraw_crop(crop: Image.Image) -> Image.Image:
    rgb = crop.convert("RGB")
    w, h = rgb.size
    mask = Image.new("L", (w, h), 0)
    src = rgb.load()
    mask_px = mask.load()
    for y in range(h):
        for x in range(w):
            r, g, b = src[x, y]
            lum = (0.299 * r + 0.587 * g + 0.114 * b)
            sat = max(r, g, b) - min(r, g, b)
            if sat < 35:
                if r > 250 and g > 250 and b > 250:
                    mask_px[x, y] = 0
                else:
                    mask_px[x, y] = 255
            else:
                mask_px[x, y] = 0
    mask = mask.filter(ImageFilter.MedianFilter(size=3))
    out = Image.new("RGBA", (w, h), (0,0,0,0))
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            if mask.getpixel((x,y)) > 0:
                r,g,b = src[x,y]
                out_px[x,y] = (r,g,b,255)
    return out

def fill_template(pdf_file: str, coords_file: str = COORDS_FILE, template_file: str = TEMPLATE) -> str:
    base = Path(pdf_file).stem
    output_file = f"{base}_output.png"
    if not Path(template_file).exists():
        raise FileNotFoundError(f"Template not found: {template_file}")
    if not Path(coords_file).exists():
        raise FileNotFoundError(f"Coords file not found: {coords_file}")

    template = Image.open(template_file).convert("RGBA")
    with open(coords_file, "r", encoding="utf-8") as f:
        mappings = json.load(f)

    pdf_img = pdf_first_page_as_pil(pdf_file, zoom=2.0)

    for i, m in enumerate(mappings):
        pdf_box = m.get("pdf_box")
        template_box = m.get("template_box")
        if not pdf_box or not template_box:
            logger.warning("Skipping invalid mapping #%s: %s", i, m)
            continue

        try:
            px1, py1, px2, py2 = map(float, pdf_box)
            px1, px2 = sorted([px1, px2]); py1, py2 = sorted([py1, py2])
            px1, py1, px2, py2 = map(int, map(round, (px1, py1, px2, py2)))
        except Exception as ex:
            logger.warning("Invalid pdf_box #%s: %s (%s)", i, pdf_box, ex)
            continue

        px1 = max(0, min(px1, pdf_img.width - 1))
        py1 = max(0, min(py1, pdf_img.height - 1))
        px2 = max(0, min(px2, pdf_img.width))
        py2 = max(0, min(py2, pdf_img.height))
        if px2 <= px1 or py2 <= py1:
            logger.warning("Skipping zero/negative pdf box #%s: %s", i, pdf_box)
            continue

        crop = pdf_img.crop((px1, py1, px2, py2))
        crop_processed = redraw_crop(crop)

        try:
            tx1, ty1, tx2, ty2 = map(float, template_box)
            tx1, tx2 = sorted([tx1, tx2]); ty1, ty2 = sorted([ty1, ty2])
            tx1, ty1, tx2, ty2 = map(int, map(round, (tx1, ty1, tx2, ty2)))
        except Exception as ex:
            logger.warning("Invalid template_box #%s: %s (%s)", i, template_box, ex)
            continue

        w = tx2 - tx1; h = ty2 - ty1
        if w <= 0 or h <= 0:
            logger.warning("Skipping invalid template area #%s size %dx%d", i, w, h)
            continue

        crop_resized = crop_processed.resize((w, h), Image.LANCZOS)
        template.alpha_composite(crop_resized, dest=(tx1, ty1))

    out_img = ImageOps.mirror(template)
    out_img.save(output_file)
    logger.info("Saved output: %s", output_file)
    return output_file

def combine_images_vertically(image_paths: List[str], output_path: str = "combined_output.png") -> str:
    imgs = [Image.open(p).convert("RGBA") for p in image_paths]
    widths, heights = zip(*(i.size for i in imgs))
    total_height = sum(heights) + max(0, (len(imgs) - 1) * 10)
    combined = Image.new("RGBA", (max(widths), total_height), (255,255,255,255))
    y = 0
    for im in imgs:
        combined.paste(im, (0, y))
        y += im.height + 10
    combined.save(output_path)
    return output_path

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        await update.message.reply_text("Please send a PDF document.")
        return
    user_id = update.message.from_user.id
    file = await update.message.document.get_file()
    user_folder = Path("uploads")
    user_folder.mkdir(exist_ok=True)
    index = len(user_sessions.get(user_id, [])) + 1
    pdf_path = str(user_folder / f"user_{user_id}_{index}.pdf")
    await file.download_to_drive(pdf_path)
    user_sessions.setdefault(user_id, []).append(pdf_path)
    count = len(user_sessions[user_id])
    await update.message.reply_text(f"📄 Got PDF {count}/5. Send more or type /done to process.")
    logger.info("User %s uploaded PDF: %s", user_id, pdf_path)
    if count >= 5:
        await process_user_pdfs(update, context)

async def process_user_pdfs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    pdfs = user_sessions.get(user_id, [])
    if not pdfs:
        await update.message.reply_text("⚠️ You haven't sent any PDFs yet.")
        return
    await update.message.reply_text("⚙️ Processing your PDFs, please wait...")
    output_images = []
    try:
        for pdf in pdfs:
            out = fill_template(pdf)
            output_images.append(out)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        user_label = f"user{user_id}"
        combined_name = f"combined_{user_label}_{timestamp}.png"
        combined = combine_images_vertically(output_images, output_path=combined_name)
        final_copy = "output.png"
        Image.open(combined).save(final_copy)
        with open(combined, "rb") as fh:
            await update.message.reply_document(fh)
        await update.message.reply_text(f"✅ Done! Saved as {combined_name} and output.png")
        logger.info("Processed and sent combined output for user %s", user_id)
    except Exception as ex:
        logger.exception("Error processing PDFs for user %s", user_id)
        await update.message.reply_text(f"❌ Error: {ex}")
    finally:
        for p in pdfs:
            try:
                os.remove(p)
            except Exception:
                pass
        for p in output_images:
            try:
                os.remove(p)
            except Exception:
                pass
        try:
            if os.path.exists("combined_output.png"):
                os.remove("combined_output.png")
        except Exception:
            pass
        user_sessions[user_id] = []

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_user_pdfs(update, context)

def start_keepalive_thread():
    try:
        from flask import Flask
    except Exception:
        logger.warning("Flask not available; keepalive disabled.")
        return
    app = Flask("keepalive")
    @app.route("/")
    def home():
        return "OK", 200
    def _run():
        port = int(os.environ.get("PORT", KEEPALIVE_PORT))
        app.run(host="0.0.0.0", port=port)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Started keepalive Flask thread on port %s", KEEPALIVE_PORT)

import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# your handlers here
# e.g.
# async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     ...

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))

    print("✅ Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Telegram бот для обработки фактур Wolt
Принимает PDF-файлы фактур и создает итоговый PDF с суммой
"""

import os
import re
import logging
from datetime import datetime
from typing import List, Dict
import tempfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, 
    Table, 
    TableStyle, 
    Paragraph, 
    Spacer,
    PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class InvoiceData:
    """Класс для хранения данных фактуры"""
    def __init__(self):
        self.invoice_number = ""
        self.date = ""
        self.period = ""
        self.earnings = 0.0
        self.tips = 0.0
        self.total = 0.0
        
    def __repr__(self):
        return f"Invoice {self.invoice_number}: {self.total} CZK"


class WoltInvoiceBot:
    """Главный класс бота"""
    
    def __init__(self):
        self.user_invoices = {}  # {user_id: [InvoiceData]}
        
    def extract_invoice_data(self, pdf_path: str) -> InvoiceData:
        """Извлекает данные из PDF фактуры Wolt"""
        invoice = InvoiceData()
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Извлекаем текст с первой страницы
                page = pdf.pages[0]
                text = page.extract_text()
                
                # Извлекаем номер фактуры
                invoice_match = re.search(r'Číslo faktury:\s*(\S+)', text)
                if invoice_match:
                    invoice.invoice_number = invoice_match.group(1)
                
                # Извлекаем дату
                date_match = re.search(r'Datum vystavení faktury:\s*(\d{2}\.\d{2}\.\d{4})', text)
                if date_match:
                    invoice.date = date_match.group(1)
                
                # Извлекаем период
                period_match = re.search(r'Za období:\s*(\d{2}\.\d{2}\.\d{4})\s*—\s*(\d{2}\.\d{2}\.\d{4})', text)
                if period_match:
                    invoice.period = f"{period_match.group(1)} — {period_match.group(2)}"
                
                # Извлекаем суммы (чешский формат: пробелы для тысяч, запятая для дробной части)
                # Ищем числа в формате: 27 399,30 или 27399,30
                earnings_match = re.search(r'Wolt kurýrské výdělky.*?(\d+(?:\s\d{3})*,\d{2})', text)
                if earnings_match:
                    # Убираем пробелы (разделители тысяч) и меняем запятую на точку
                    earnings_str = earnings_match.group(1).replace(' ', '').replace(',', '.')
                    invoice.earnings = float(earnings_str)
                
                # Чаевые
                tips_match = re.search(r'Spropitné.*?(\d+(?:\s\d{3})*,\d{2})', text)
                if tips_match:
                    tips_str = tips_match.group(1).replace(' ', '').replace(',', '.')
                    invoice.tips = float(tips_str)
                
                # Общая сумма
                total_match = re.search(r'Celkem k úhradě\s*(\d+(?:\s\d{3})*,\d{2})', text)
                if total_match:
                    total_str = total_match.group(1).replace(' ', '').replace(',', '.')
                    invoice.total = float(total_str)
                
                logger.info(f"Extracted invoice: {invoice}")
                
        except Exception as e:
            logger.error(f"Error extracting invoice data: {e}")
            raise
            
        return invoice
    
    def create_summary_pdf(self, invoices: List[InvoiceData], output_path: str):
        """Создает итоговый PDF со всеми фактурами"""
        # Сортируем фактуры по дате (от старых к новым)
        def parse_date(date_str):
            """Парсит дату формата DD.MM.YYYY"""
            try:
                from datetime import datetime as dt
                return dt.strptime(date_str, '%d.%m.%Y')
            except:
                return dt.min
        
        sorted_invoices = sorted(invoices, key=lambda inv: parse_date(inv.date))
        
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )
        
        styles = getSampleStyleSheet()
        story = []
        
        # Заголовок
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=30,
            alignment=1  # Center
        )
        
        title = Paragraph("Итоговая сводка по фактурам Wolt", title_style)
        story.append(title)
        
        # Дата создания отчета
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=1
        )
        report_date = Paragraph(
            f"Создано: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            date_style
        )
        story.append(report_date)
        story.append(Spacer(1, 1*cm))
        
        # Таблица с фактурами
        table_data = [
            ['Номер фактуры', 'Дата', 'Период', 'Заработок', 'Чаевые', 'Итого']
        ]
        
        total_earnings = 0
        total_tips = 0
        total_amount = 0
        
        for inv in sorted_invoices:
            table_data.append([
                inv.invoice_number,
                inv.date,
                inv.period,
                f"{inv.earnings:,.2f}".replace(',', ' ').replace('.', ','),
                f"{inv.tips:,.2f}".replace(',', ' ').replace('.', ','),
                f"{inv.total:,.2f}".replace(',', ' ').replace('.', ',')
            ])
            total_earnings += inv.earnings
            total_tips += inv.tips
            total_amount += inv.total
        
        # Итоговая строка
        table_data.append([
            Paragraph('<b>ИТОГО</b>', styles['Normal']),
            '', '',
            Paragraph(f"<b>{total_earnings:,.2f}</b>".replace(',', ' ').replace('.', ','), styles['Normal']),
            Paragraph(f"<b>{total_tips:,.2f}</b>".replace(',', ' ').replace('.', ','), styles['Normal']),
            Paragraph(f"<b>{total_amount:,.2f}</b>".replace(',', ' ').replace('.', ','), styles['Normal'])
        ])
        
        table = Table(table_data, colWidths=[4*cm, 2.5*cm, 4*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        
        table.setStyle(TableStyle([
            # Заголовок
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Данные
            ('FONTNAME', (0, 1), (-1, -2), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -2), 9),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 1), (2, -1), 'LEFT'),
            
            # Итоговая строка
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E8F4F8')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 11),
            
            # Границы
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#4A90E2')),
            ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#4A90E2')),
            
            # Отступы
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 1*cm))
        
        # Итоговая сумма крупным шрифтом
        summary_style = ParagraphStyle(
            'SummaryStyle',
            parent=styles['Normal'],
            fontSize=18,
            textColor=colors.HexColor('#4A90E2'),
            alignment=2,  # Right
            fontName='Helvetica-Bold'
        )
        
        summary_text = f"Общая сумма: {total_amount:,.2f} CZK".replace(',', ' ').replace('.', ',')
        story.append(Paragraph(summary_text, summary_style))
        
        # Дополнительная информация
        story.append(Spacer(1, 1*cm))
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey
        )
        
        info_text = f"Количество фактур: {len(invoices)}"
        story.append(Paragraph(info_text, info_style))
        
        # Собираем PDF
        doc.build(story)
        logger.info(f"Summary PDF created: {output_path}")


# Инициализация бота
bot = WoltInvoiceBot()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """
👋 Добро пожаловать в Wolt Invoice Bot!

Этот бот поможет вам обработать фактуры от Wolt и создать итоговый PDF.

📋 Как это работает:
1. Отправьте мне один или несколько PDF файлов с фактурами Wolt
2. Напишите /summary когда хотите создать итоговый PDF
3. Скачайте созданный итоговый документ

🗑️ Для удаления текущих фактур используйте /clear

Начните с того, что отправьте мне свои фактуры!
"""
    await update.message.reply_text(welcome_message)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик PDF документов"""
    user_id = update.effective_user.id
    document = update.message.document
    
    # Проверяем, что это PDF
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ Пожалуйста, отправляйте только PDF файлы.")
        return
    
    await update.message.reply_text("📄 Обрабатываю фактуру...")
    
    try:
        # Скачиваем файл
        file = await context.bot.get_file(document.file_id)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            await file.download_to_drive(tmp_file.name)
            tmp_path = tmp_file.name
        
        # Извлекаем данные
        invoice = bot.extract_invoice_data(tmp_path)
        
        # Удаляем временный файл
        os.unlink(tmp_path)
        
        # Сохраняем для пользователя
        if user_id not in bot.user_invoices:
            bot.user_invoices[user_id] = []
        
        bot.user_invoices[user_id].append(invoice)
        
        # Отправляем подтверждение
        count = len(bot.user_invoices[user_id])
        message = f"""
✅ Фактура добавлена!

📋 Номер: {invoice.invoice_number}
📅 Дата: {invoice.date}
📆 Период: {invoice.period}
💰 Итого: {invoice.total:,.2f} CZK

📊 Всего фактур: {count}

Для создания итогового PDF напишите /summary
"""
        await update.message.reply_text(message.replace(',', ' ').replace('.', ','))
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при обработке фактуры: {str(e)}\n"
            "Проверьте, что это правильный формат фактуры Wolt."
        )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает итоговый PDF"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text(
            "❌ У вас нет фактур для обработки.\n"
            "Сначала отправьте мне PDF фактуры от Wolt."
        )
        return
    
    await update.message.reply_text("🔄 Создаю итоговый PDF...")
    
    try:
        invoices = bot.user_invoices[user_id]
        
        # Создаем временный файл для итогового PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            output_path = tmp_file.name
        
        # Генерируем PDF
        bot.create_summary_pdf(invoices, output_path)
        
        # Отправляем файл
        total = sum(inv.total for inv in invoices)
        caption = f"📊 Итого по {len(invoices)} фактурам\n💰 Общая сумма: {total:,.2f} CZK".replace(',', ' ').replace('.', ',')
        
        with open(output_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=f"wolt_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                caption=caption
            )
        
        # Удаляем временный файл
        os.unlink(output_path)
        
        await update.message.reply_text(
            "✅ Готово! Для удаления фактур используйте /clear"
        )
        
    except Exception as e:
        logger.error(f"Error creating summary: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при создании итога: {str(e)}"
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очищает сохраненные фактуры пользователя"""
    user_id = update.effective_user.id
    
    if user_id in bot.user_invoices:
        count = len(bot.user_invoices[user_id])
        bot.user_invoices[user_id] = []
        await update.message.reply_text(
            f"✅ Удалено {count} фактур.\n"
            "Можете отправить новые фактуры."
        )
    else:
        await update.message.reply_text("ℹ️ У вас нет фактур для удаления.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий статус"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text("ℹ️ У вас пока нет фактур.")
        return
    
    invoices = bot.user_invoices[user_id]
    
    # Сортируем по дате
    def parse_date(date_str):
        """Парсит дату формата DD.MM.YYYY"""
        try:
            from datetime import datetime as dt
            return dt.strptime(date_str, '%d.%m.%Y')
        except:
            return dt.min
    
    sorted_invoices = sorted(invoices, key=lambda inv: parse_date(inv.date))
    total = sum(inv.total for inv in sorted_invoices)
    
    message = f"""
📊 Текущее состояние:

Количество фактур: {len(sorted_invoices)}
Общая сумма: {total:,.2f} CZK

📋 Фактуры:
""".replace(',', ' ').replace('.', ',')
    
    for inv in sorted_invoices:
        message += f"• {inv.date} - {inv.invoice_number}: {inv.total:,.2f} CZK\n".replace(',', ' ').replace('.', ',')
    
    message += "\nДля создания итога: /summary"
    
    await update.message.reply_text(message)


def main():
    """Запуск бота"""
    # ВАЖНО: Вставьте сюда ваш токен от @BotFather
    TOKEN = 
    
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Вставьте ваш токен бота в переменную TOKEN!")
        print("Получите токен у @BotFather в Telegram")
        return
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    
    # Запускаем бота
    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
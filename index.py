#!/usr/bin/env python3
"""
Telegram бот для обработки фактур Wolt
Принимает PDF-файлы фактур и создает итоговый PDF с суммой
"""

from dotenv import load_dotenv
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
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

load_dotenv()

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
        # Используем стандартные шрифты - они отлично работают с английским
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'
        
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
            alignment=TA_CENTER,
            fontName=font_name_bold
        )
        
        title = Paragraph("Wolt Invoices Summary", title_style)
        story.append(title)
        
        # Дата создания отчета
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=TA_CENTER,
            fontName=font_name
        )
        report_date = Paragraph(
            f"Created: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            date_style
        )
        story.append(report_date)
        story.append(Spacer(1, 1*cm))
        
        # Таблица с фактурами
        table_data = [
            ['Invoice Number', 'Date', 'Period', 'Earnings', 'Tips', 'Total']
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
            Paragraph('<b>TOTAL</b>', styles['Normal']),
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
            ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            
            # Данные
            ('FONTNAME', (0, 1), (-1, -2), font_name),
            ('FONTSIZE', (0, 1), (-1, -2), 9),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 1), (2, -1), 'LEFT'),
            
            # Итоговая строка
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E8F4F8')),
            ('FONTNAME', (0, -1), (-1, -1), font_name_bold),
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
            alignment=TA_RIGHT,
            fontName=font_name_bold
        )
        
        summary_text = f"Total Amount: {total_amount:,.2f} CZK".replace(',', ' ').replace('.', ',')
        story.append(Paragraph(summary_text, summary_style))
        
        # Дополнительная информация
        story.append(Spacer(1, 1*cm))
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            fontName=font_name
        )
        
        info_text = f"Number of invoices: {len(invoices)}"
        story.append(Paragraph(info_text, info_style))
        
        # Собираем PDF
        doc.build(story)
        logger.info(f"Summary PDF created: {output_path}")
    
    def create_tax_pdf(self, invoices: List[InvoiceData], output_path: str):
        """Creates tax calculation PDF for students"""
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'
        
        # Calculate totals
        total_income = sum(inv.total for inv in invoices)
        expenses_60 = total_income * 0.6
        tax_base = total_income - expenses_60
        tax_15 = tax_base * 0.15
        taxpayer_deduction = 30840
        student_deduction = 4020
        total_deductions = taxpayer_deduction + student_deduction
        final_tax = max(0, tax_15 - total_deductions)
        
        needs_health = total_income >= 100000
        needs_social = total_income >= 100000
        needs_prepayment = total_income >= 50000
        
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
        
        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName=font_name_bold
        )
        story.append(Paragraph("Student Tax Calculation 2025", title_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%d.%m.%Y')}", 
                               ParagraphStyle('subtitle', parent=styles['Normal'], alignment=TA_CENTER, textColor=colors.grey, fontSize=10)))
        story.append(Spacer(1, 1*cm))
        
        # Income Summary
        story.append(Paragraph("INCOME SUMMARY", ParagraphStyle('h2', parent=styles['Heading2'], fontName=font_name_bold, fontSize=14, textColor=colors.HexColor('#4A90E2'))))
        story.append(Spacer(1, 0.3*cm))
        
        income_data = [
            ['Description', 'Amount (CZK)'],
            ['Total Income (Celkem prijmy)', f"{total_income:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Number of Invoices', str(len(invoices))],
        ]
        
        income_table = Table(income_data, colWidths=[10*cm, 5*cm])
        income_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(income_table)
        story.append(Spacer(1, 0.8*cm))
        
        # Tax Calculation
        story.append(Paragraph("TAX CALCULATION (Vypocet dane)", ParagraphStyle('h2', parent=styles['Heading2'], fontName=font_name_bold, fontSize=14, textColor=colors.HexColor('#4A90E2'))))
        story.append(Spacer(1, 0.3*cm))
        
        tax_data = [
            ['Item', 'Amount (CZK)'],
            ['Income (Prijmy)', f"{total_income:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Expenses 60% (Vydaje 60%)', f"-{expenses_60:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Tax Base (Zaklad dane)', f"{tax_base:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Tax 15%', f"{tax_15:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Taxpayer Deduction (Sleva na poplatnika)', f"-{taxpayer_deduction:,.2f}".replace(',', ' ').replace('.', ',')],
            ['Student Deduction (Sleva na studenta)', f"-{student_deduction:,.2f}".replace(',', ' ').replace('.', ',')],
        ]
        
        tax_table = Table(tax_data, colWidths=[10*cm, 5*cm])
        tax_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(tax_table)
        story.append(Spacer(1, 0.5*cm))
        
        # Final tax to pay
        final_box = Paragraph(f"<b>FINAL TAX TO PAY: {final_tax:,.2f} CZK</b>".replace(',', ' ').replace('.', ','),
                              ParagraphStyle('final', parent=styles['Normal'], fontSize=16, fontName=font_name_bold, 
                                           textColor=colors.HexColor('#4A90E2'), alignment=TA_CENTER,
                                           borderColor=colors.HexColor('#4A90E2'), borderWidth=2, borderPadding=10))
        story.append(final_box)
        story.append(Spacer(1, 0.8*cm))
        
        # Insurance
        story.append(Paragraph("INSURANCE REQUIREMENTS (Pojisteni)", ParagraphStyle('h2', parent=styles['Heading2'], fontName=font_name_bold, fontSize=14, textColor=colors.HexColor('#4A90E2'))))
        story.append(Spacer(1, 0.3*cm))
        
        insurance_data = [
            ['Type', 'Required?', 'Notes'],
            ['Health Insurance (Zdravotni)', 
             'YES' if needs_health else 'NO',
             f"Min. {2968*12:,} CZK/year".replace(',', ' ') if needs_health else 'Income < 100,000 CZK'],
            ['Social Insurance (Socialni)', 
             'YES' if needs_social else 'NO',
             f"Min. {3267*12:,} CZK/year".replace(',', ' ') if needs_social else 'Income < 100,000 CZK'],
            ['Tax Prepayments (Zalohy)', 
             'YES' if needs_prepayment else 'NO',
             'Required' if needs_prepayment else 'Income < 50,000 CZK'],
        ]
        
        insurance_table = Table(insurance_data, colWidths=[5*cm, 3*cm, 7*cm])
        insurance_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (1, 1), (1, -1), colors.HexColor('#E8F4F8')),
        ]))
        story.append(insurance_table)
        story.append(Spacer(1, 0.8*cm))
        
        # Important Dates
        story.append(Paragraph("IMPORTANT DEADLINES (Terminy)", ParagraphStyle('h2', parent=styles['Heading2'], fontName=font_name_bold, fontSize=14, textColor=colors.HexColor('#4A90E2'))))
        story.append(Spacer(1, 0.3*cm))
        
        deadlines_data = [
            ['Document', 'Deadline'],
            ['Overview of Payments (Prehled plateb)', '1 February 2026'],
            ['Tax Return (Danove priznani)', '1 April 2026'],
        ]
        
        deadlines_table = Table(deadlines_data, colWidths=[10*cm, 5*cm])
        deadlines_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), font_name_bold),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(deadlines_table)
        story.append(Spacer(1, 1*cm))
        
        # Disclaimer
        disclaimer_style = ParagraphStyle('disclaimer', parent=styles['Normal'], fontSize=9, textColor=colors.grey, 
                                         fontName=font_name, alignment=TA_CENTER)
        story.append(Paragraph("⚠️ IMPORTANT NOTICE ⚠️", ParagraphStyle('warn', parent=disclaimer_style, fontSize=10, fontName=font_name_bold, textColor=colors.red)))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("This is an estimated calculation for informational purposes only.", disclaimer_style))
        story.append(Paragraph("For accurate tax calculation, please consult:", disclaimer_style))
        story.append(Paragraph("• Accountant (ucetni) • Tax Office (financni urad) • Your insurance company", disclaimer_style))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("💡 TIP: You can claim actual expenses instead of 60% flat-rate (fuel, repairs, phone, etc.)", 
                             ParagraphStyle('tip', parent=disclaimer_style, fontSize=9, textColor=colors.HexColor('#4A90E2'))))
        
        doc.build(story)
        logger.info(f"Tax PDF created: {output_path}")


# Инициализация бота
bot = WoltInvoiceBot()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """
👋 Welcome to Wolt Faktury Bot!

This bot helps you process Wolt invoices and create summary PDFs.

📋 Commands:
/start - Start the bot
/status - View uploaded invoices
/summary - Create invoices PDF report
/taxes - 💰 Calculate student taxes
/taxpdf - 📄 Generate tax PDF report
/clear - Clear all invoices

Send your Wolt PDF invoices to get started!
"""
    await update.message.reply_text(welcome_message)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик PDF документов"""
    user_id = update.effective_user.id
    document = update.message.document
    
    # Проверяем, что это PDF
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ Please send only PDF files.")
        return
    
    await update.message.reply_text("📄 Processing invoice...")
    
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
✅ Invoice added!

📋 Number: {invoice.invoice_number}
📅 Date: {invoice.date}
📆 Period: {invoice.period}
💰 Total: {invoice.total:,.2f} CZK

📊 Total invoices: {count}

Create summary: /summary
Calculate taxes: /taxes
"""
        await update.message.reply_text(message.replace(',', ' ').replace('.', ','))
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await update.message.reply_text(
            f"❌ Error processing invoice: {str(e)}\n"
            "Please check that this is a valid Wolt invoice format."
        )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает итоговый PDF"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text(
            "❌ No invoices found.\n"
            "Please send Wolt PDF invoices first."
        )
        return
    
    await update.message.reply_text("🔄 Creating summary PDF...")
    
    try:
        invoices = bot.user_invoices[user_id]
        
        # Создаем временный файл для итогового PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            output_path = tmp_file.name
        
        # Генерируем PDF
        bot.create_summary_pdf(invoices, output_path)
        
        # Отправляем файл
        total = sum(inv.total for inv in invoices)
        caption = f"📊 Summary of {len(invoices)} invoices\n💰 Total: {total:,.2f} CZK".replace(',', ' ').replace('.', ',')
        
        with open(output_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=f"wolt_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                caption=caption
            )
        
        # Удаляем временный файл
        os.unlink(output_path)
        
        await update.message.reply_text(
            "✅ Done! Use /clear to delete invoices"
        )
        
    except Exception as e:
        logger.error(f"Error creating summary: {e}")
        await update.message.reply_text(
            f"❌ Error creating summary: {str(e)}"
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очищает сохраненные фактуры пользователя"""
    user_id = update.effective_user.id
    
    if user_id in bot.user_invoices:
        count = len(bot.user_invoices[user_id])
        bot.user_invoices[user_id] = []
        await update.message.reply_text(
            f"✅ Deleted {count} invoices.\n"
            "You can send new invoices now."
        )
    else:
        await update.message.reply_text("ℹ️ No invoices to delete.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий статус"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text("ℹ️ No invoices yet.")
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
📊 Current Status:

Invoices: {len(sorted_invoices)}
Total: {total:,.2f} CZK

📋 Invoices:
""".replace(',', ' ').replace('.', ',')
    
    for inv in sorted_invoices:
        message += f"• {inv.date} - {inv.invoice_number}: {inv.total:,.2f} CZK\n".replace(',', ' ').replace('.', ',')
    
    message += "\nCreate summary: /summary"
    
    await update.message.reply_text(message)


async def calculate_taxes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tax calculator for students"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text(
            "❌ No invoices found.\n"
            "Please add invoices first."
        )
        return
    
    invoices = bot.user_invoices[user_id]
    
    # Calculate total income
    total_income = sum(inv.total for inv in invoices)
    
    # Calculations
    expenses_60 = total_income * 0.6  # 60% flat-rate expenses
    tax_base = total_income - expenses_60
    
    # Tax 15%
    tax_15 = tax_base * 0.15
    
    # Deductions
    taxpayer_deduction = 30840  # Sleva na poplatníka
    student_deduction = 4020    # Sleva na studenta
    total_deductions = taxpayer_deduction + student_deduction
    
    # Final tax
    final_tax = max(0, tax_15 - total_deductions)
    
    # Check thresholds
    needs_health_insurance = total_income >= 100000
    needs_social_insurance = total_income >= 100000
    needs_tax_prepayment = total_income >= 50000
    
    message = f"""
📊 TAX CALCULATION FOR STUDENT (2025)

💰 Total Income: {total_income:,.2f} CZK

📉 TAX CALCULATION:
• Income (prijmy): {total_income:,.2f} CZK
• Expenses 60%: -{expenses_60:,.2f} CZK
• Tax base (zaklad dane): {tax_base:,.2f} CZK
• Tax 15%: {tax_15:,.2f} CZK
• Taxpayer deduction: -{taxpayer_deduction:,.2f} CZK
• Student deduction: -{student_deduction:,.2f} CZK
━━━━━━━━━━━━━━━━━━━
💵 To pay: {final_tax:,.2f} CZK

🏥 INSURANCE (pojisteni):
""".replace(',', ' ').replace('.', ',')
    
    if needs_health_insurance:
        min_health = 2968 * 12  # Minimum per year
        message += f"⚠️ Health (zdravotni): YES (min. {min_health:,.2f} CZK/year)\n"
    else:
        message += "✅ Health (zdravotni): NO (income < 100,000 CZK)\n"
    
    if needs_social_insurance:
        min_social = 3267 * 12  # Minimum per year
        message += f"⚠️ Social (socialni): YES (min. {min_social:,.2f} CZK/year)\n"
    else:
        message += "✅ Social (socialni): NO (income < 100,000 CZK)\n"
    
    message += f"\n📅 TAX PREPAYMENTS (zalohy na dan):\n"
    if needs_tax_prepayment:
        message += "⚠️ YES - you must pay prepayments\n"
    else:
        message += "✅ NO - income < 50,000 CZK\n"
    
    message += f"""
📋 DEADLINES (terminy):
• Overview of payments: by 1.2.2026
  (prehled plateb)
• Tax return: by 1.4.2026
  (danove priznani)

⚠️ IMPORTANT:
This is an estimated calculation!
For accurate calculation consult:
• Accountant (ucetni)
• Tax office (financni urad)
• Your insurance company

💡 TIP: You can claim actual expenses
instead of 60% flat-rate
(fuel, repairs, phone, etc.)

📄 Generate PDF report: /taxpdf
""".replace(',', ' ').replace('.', ',')
    
    await update.message.reply_text(message)


async def tax_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates tax calculation PDF"""
    user_id = update.effective_user.id
    
    if user_id not in bot.user_invoices or not bot.user_invoices[user_id]:
        await update.message.reply_text(
            "❌ No invoices found.\n"
            "Please add invoices first."
        )
        return
    
    await update.message.reply_text("🔄 Creating tax PDF...")
    
    try:
        invoices = bot.user_invoices[user_id]
        
        # Создаем временный файл для PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            output_path = tmp_file.name
        
        # Генерируем PDF
        bot.create_tax_pdf(invoices, output_path)
        
        # Отправляем файл
        total = sum(inv.total for inv in invoices)
        caption = f"📊 Student Tax Report\n💰 Total income: {total:,.2f} CZK".replace(',', ' ').replace('.', ',')
        
        with open(output_path, 'rb') as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=f"tax_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                caption=caption
            )
        
        # Удаляем временный файл
        os.unlink(output_path)
        
        await update.message.reply_text(
            "✅ Tax report generated!\n"
            "⚠️ This is an estimate - consult an accountant for accurate calculation."
        )
        
    except Exception as e:
        logger.error(f"Error creating tax PDF: {e}")
        await update.message.reply_text(
            f"❌ Error creating tax report: {str(e)}"
        )


def main():
    """Запуск бота"""
    # ВАЖНО: Вставьте сюда ваш токен от @BotFather
    TOKEN = os.getenv('BOT_TOKEN')
    
    if not TOKEN:
        print("❌ ERROR: Add your bot token to .env file!")
        print("BOT_TOKEN=your_token_from_BotFather")
        return
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("taxes", calculate_taxes))
    application.add_handler(CommandHandler("taxpdf", tax_pdf))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    
    # Запускаем бота
    print("🤖 Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
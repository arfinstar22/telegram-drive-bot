"""Data models for Task 3C Receipt & Document Intelligence Core.

Structured representations for:
- Receipt items (name, quantity, unit price, total price, confidence)
- Receipt data (merchant, transaction date/time, totals, taxes, discounts, payments, items)
- Document data (type, number, date, subject, sender, recipient, organization, metadata)
- Overall DocumentIntelligenceResult with warnings, explanation, and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ReceiptItem:
    """Individual line item detected on a receipt."""
    name: str | None = None
    quantity: float | None = None
    unit_price: int | float | None = None
    total_price: int | float | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class ReceiptData:
    """Structured receipt extraction details."""
    merchant_name: str | None = None
    merchant_address: str | None = None
    receipt_number: str | None = None
    transaction_date: str | None = None
    transaction_time: str | None = None
    subtotal: int | float | None = None
    tax: int | float | None = None
    service_charge: int | float | None = None
    discount: int | float | None = None
    total: int | float | None = None
    paid_amount: int | float | None = None
    change_amount: int | float | None = None
    payment_method: str | None = None
    items: list[ReceiptItem] = field(default_factory=list)
    currency: str | None = "IDR"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "merchant_name": self.merchant_name,
            "merchant_address": self.merchant_address,
            "receipt_number": self.receipt_number,
            "transaction_date": self.transaction_date,
            "transaction_time": self.transaction_time,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "service_charge": self.service_charge,
            "discount": self.discount,
            "total": self.total,
            "paid_amount": self.paid_amount,
            "change_amount": self.change_amount,
            "payment_method": self.payment_method,
            "items": [item.to_dict() for item in self.items],
            "currency": self.currency,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class DocumentData:
    """Structured generic document extraction details."""
    document_type: str | None = None
    document_number: str | None = None
    date: str | None = None
    subject: str | None = None
    sender: str | None = None
    recipient: str | None = None
    organization: str | None = None
    attachment: str | None = None
    names: list[str] = field(default_factory=list)
    reference_numbers: list[str] = field(default_factory=list)
    important_dates: list[str] = field(default_factory=list)
    important_amounts: list[dict[str, Any]] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phone_numbers: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "document_number": self.document_number,
            "date": self.date,
            "subject": self.subject,
            "sender": self.sender,
            "recipient": self.recipient,
            "organization": self.organization,
            "attachment": self.attachment,
            "names": self.names,
            "reference_numbers": self.reference_numbers,
            "important_dates": self.important_dates,
            "important_amounts": self.important_amounts,
            "emails": self.emails,
            "phone_numbers": self.phone_numbers,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class DocumentIntelligenceResult:
    """Top-level result of Receipt and Document Intelligence parsing."""
    status: str  # "classified" | "ambiguous" | "unknown"
    document_type: str  # "receipt", "official_letter", "invoice", "academic_document", etc.
    receipt: ReceiptData | None = None
    document: DocumentData | None = None
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    explanation: list[str] = field(default_factory=list)
    raw_text: str = ""
    normalized_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "document_type": self.document_type,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "document": self.document.to_dict() if self.document else None,
            "warnings": self.warnings,
            "confidence": round(self.confidence, 4),
            "explanation": self.explanation,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
        }


# Alias for compatibility with section 3 specifications
IntelligenceResult = DocumentIntelligenceResult

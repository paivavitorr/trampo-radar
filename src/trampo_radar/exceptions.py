"""Exceções customizadas do domínio TrampoRadar."""

from __future__ import annotations


class DomainError(Exception):
    """Erro base do domínio."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFoundError(DomainError):
    """Entidade não encontrada."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class EmailIntegrationError(DomainError):
    """Erro ao conectar ou ler e-mails via IMAP/SMTP."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)


class ScrapingError(DomainError):
    """Erro ao buscar vagas no LinkedIn ou páginas externas."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)


class ResumeGenerationError(DomainError):
    """Erro na geração do currículo via IA ou renderização PDF."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)


class NotificationError(DomainError):
    """Erro ao enviar notificação para Telegram ou SMTP."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=502)

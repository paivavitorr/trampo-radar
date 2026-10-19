# TrampoRadar

Serviço em Python e FastAPI para captura diária de vagas via alertas de e-mail (IMAP) e busca ativa no LinkedIn, com filtragem de relevância, notificações no Telegram e geração de currículo em PDF adaptado com IA.

## Funcionalidades

- Leitura de alertas de vagas na caixa de e-mail via IMAP (LinkedIn, Gupy, Indeed, Glassdoor, Programathor, Trampos).
- Scraper assíncrono do LinkedIn com rate limiting, retry e coleta da descrição completa da vaga.
- Controle de duplicados (`seen.json`) e filtros por palavras-chave, expressões regulares, empresas, localização e tempo de publicação.
- Envio diário das vagas filtradas para o Telegram ou resumo por e-mail (SMTP).
- Adaptação de currículo via IA (compatível com Groq/OpenAI) e geração de PDF A4 ao responder `/resume` em uma vaga no Telegram ou via API.

## Instalação e Uso

1. Instale as dependências:
```bash
uv sync
```

2. Configure as variáveis de ambiente:
```bash
cp .env.example .env
```
Preencha no `.env` as credenciais do e-mail (`IMAP_USER`, `IMAP_PASSWORD`), do Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) e da IA (`AI_API_KEY`).

3. Ajuste os filtros de busca e os dados do seu currículo base no arquivo `config.yaml`.

4. Inicie a aplicação:
```bash
uv run uvicorn trampo_radar.main:app --reload --port 8000
```

## Endpoints

- `GET /health` - Status da aplicação e integrações
- `GET /jobs` - Lista as vagas coletadas no cache
- `GET /jobs/{job_id}` - Detalhes de uma vaga específica
- `POST /jobs/scan` - Dispara a varredura imediatamente
- `POST /jobs/{job_id}/resume` - Gera e retorna o currículo adaptado em PDF para a vaga

## Testes e Qualidade

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

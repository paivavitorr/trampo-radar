# TrampoRadar 📬💼

Automação diária em **Python + FastAPI** que combina:
1. **Leitura do seu E-mail via IMAP** (alertas de vagas do LinkedIn, Gupy, Indeed, Glassdoor, Programathor, etc.)
2. **Scraper direto do LinkedIn** (busca ativa com rate-limit, retry e busca de descrição completa)
3. **Deduplicação e Filtragem Inteligente** (`seen.json` + palavras-chave, regex `/.../i`, empresas, localização e idade máxima da vaga)
4. **Notificações + Geração de Currículo em PDF com IA (`/resume`)**:
   - Envia as vagas novas todos os dias para o **Telegram** (e/ou um resumo diário por **E-mail SMTP**).
   - Responda `/resume` a qualquer vaga no Telegram (ou chame `POST /jobs/{id}/resume` na API) para que a IA (Groq/OpenAI) adapte seu currículo exclusivamente com seus dados reais do `config.yaml` e envie o **PDF A4 pronto**!

---

## Como configurar e rodar

### 1. Instalar dependências (via `uv`)
```bash
cd /home/paiva/projects/thinks/github/repos/trampo-radar
uv sync
```

### 2. Configurar credenciais no `.env`
```bash
cp .env.example .env
```
Edite o `.env`:
- **`IMAP_USER` / `IMAP_PASSWORD`**: Seu e-mail e uma **Senha de App** (no Gmail: *Conta do Google → Segurança → Verificação em duas etapas → Senhas de app*).
- **`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`**: Token do `@BotFather` e o ID numérico do seu chat.
- **`AI_API_KEY`**: Sua chave da Groq (`https://console.groq.com`) ou OpenAI.

### 3. Ajustar filtros e seu currículo base no `config.yaml`
- Configure o horário diário em `schedule.daily_hour` / `schedule.daily_minute`.
- Ajuste os termos de busca em `linkedin.keywords` e os filtros em `filters`.
- Preencha a seção `profile` com suas experiências, projetos, skills e formação (usados pela IA para gerar o PDF adaptado).

### 4. Executar o servidor FastAPI (Scheduler + Bot + API)
```bash
uv run uvicorn trampo_radar.main:app --reload --port 8000
```

Acesse a documentação interativa (Swagger UI) em:
- `http://localhost:8000/docs`

### Principais Endpoints da API
- `GET /health` — Status do IMAP, LinkedIn Scraper, Telegram, IA e horário agendado.
- `GET /jobs` — Lista as últimas vagas relevantes capturadas.
- `POST /jobs/scan` — Dispara imediatamente a varredura de E-mail + LinkedIn sob demanda.
- `POST /jobs/{job_id}/resume` — Gera e faz download do PDF do currículo adaptado para a vaga `{job_id}`.

---

## Qualidade de Código e Testes
Seguindo os padrões de `contexto-projetos` (`ruff`, `mypy --strict`, `pytest`):
```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=trampo_radar
```

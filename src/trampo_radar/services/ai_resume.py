"""Serviço de adaptação de currículo via LLM (compatível com Groq/OpenAI)."""

from __future__ import annotations

import json
import re

import httpx

from trampo_radar.config import AIConfig, ProfileConfig
from trampo_radar.exceptions import ResumeGenerationError
from trampo_radar.models.job import Job
from trampo_radar.schemas.job import GeneratedResume

MAX_DESCRIPTION_CHARS = 1500
TEMPERATURE = 0.2


def system_prompt() -> str:
    """Prompt de sistema para adaptação fiel do currículo à vaga."""
    return """Você é um assistente especialista em currículos. Sua tarefa é adaptar o
perfil profissional do usuário para cada vaga de emprego informada.

REGRAS OBRIGATORIAS:
1. Use EXCLUSIVAMENTE os dados do perfil informado. NUNCA invente cargo,
   empresa, habilidade, idioma, formacao ou projeto.
2. Adapte o conteudo a vaga: reordene secoes, reescreva o resumo e as
   descricoes com foco nos requisitos da vaga, sem distorcer fatos.
3. Se um requisito da vaga nao existir no perfil, mencione isso no campo
   "observacoes"; nao o adicione como se fosse real.
4. Pode omitir secoes irrelevantes a vaga, mas nunca substitui-las por
   conteudo inventado.
5. Escreva em portugues do Brasil, salvo se a vaga exigir outro idioma.
6. Responda APENAS com um JSON valido, sem markdown, sem texto, sem comentarios.

FORMATO DE RESPOSTA:
Um unico objeto JSON. Cada chave e o campo "id" de uma vaga e o valor e o
curriculo correspondente, com a estrutura:
{ "resumo":      string (max ~600 chars),
  "habilidades": [string] (max 15 itens),
  "experiencia": [ { "cargo": string, "empresa": string,
                     "periodo": string, "descricao": [string] (max 3 itens) } ],
  "projetos":    [ { "nome": string, "link": string, "descricao": string } ],
  "formacao":    [ { "curso": string, "instituicao": string, "periodo": string } ],
  "idiomas":     [ { "idioma": string, "nivel": string } ],
  "observacoes": string }"""


def truncate_text(text: str, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    """Trunca a descrição sem quebrar caracteres Unicode."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def build_messages(jobs: list[Job], profile: ProfileConfig) -> tuple[str, str]:
    """Constrói o par (system_prompt, user_prompt) para o lote de vagas."""
    profile_json = profile.model_dump_json()
    jobs_payload = [
        {
            "id": j.id,
            "title": j.title,
            "seniority_level": j.seniority_level,
            "description": truncate_text(j.description),
        }
        for j in jobs
    ]
    jobs_json = json.dumps(jobs_payload, ensure_ascii=False)
    user_msg = (
        "PERFIL DO USUARIO (unica fonte de verdade, em JSON):\n"
        f"{profile_json}\n\n"
        'VAGAS (gere um curriculo para cada uma, usando o "id" como chave):\n'
        f"{jobs_json}"
    )
    return system_prompt(), user_msg


def _clean_json_fence(raw: str) -> str:
    """Remove blocos ```json ... ``` caso o modelo insira fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class AIResumeService:
    """Cliente assíncrono para gerar currículos adaptados usando endpoint OpenAI-compatible."""

    def __init__(self, ai_cfg: AIConfig, profile: ProfileConfig) -> None:
        self._cfg = ai_cfg
        self._profile = profile

    def is_configured(self) -> bool:
        return bool(self._cfg.enable and self._cfg.api_token)

    async def generate_resumes(self, jobs: list[Job]) -> dict[str, GeneratedResume]:
        """Gera um dicionário {job_id: GeneratedResume} para as vagas informadas."""
        if not self.is_configured():
            raise ResumeGenerationError(
                "A IA não está configurada. Ative `ai.enable` no config.yaml e defina AI_API_KEY."
            )
        if not jobs:
            return {}

        sys_msg, usr_msg = build_messages(jobs, self._profile)
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": usr_msg},
            ],
            "max_tokens": self._cfg.max_tokens,
            "temperature": TEMPERATURE,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._cfg.api_token}",
        }
        endpoint = f"{self._cfg.base_url.rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ResumeGenerationError(f"Erro ao chamar API da IA: {exc}") from exc

        if resp.status_code != 200:
            raise ResumeGenerationError(f"IA respondeu {resp.status_code}: {resp.text.strip()}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ResumeGenerationError("A IA não retornou choices.")

        first = choices[0]
        if first.get("finish_reason") == "length":
            raise ResumeGenerationError("Resposta da IA truncada pelo limite de max_tokens.")

        raw_content = str(first.get("message", {}).get("content", ""))
        cleaned = _clean_json_fence(raw_content)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ResumeGenerationError(f"IA não devolveu JSON válido: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ResumeGenerationError("Formato inesperado da resposta da IA.")

        result: dict[str, GeneratedResume] = {}
        for job in jobs:
            if job.id not in parsed:
                raise ResumeGenerationError(f"Resposta da IA sem currículo para a vaga {job.id}")
            result[job.id] = GeneratedResume.model_validate(parsed[job.id])

        return result

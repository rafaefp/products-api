#!/usr/bin/env python3
import os
import re
import json
import requests
from typing import List, Dict, Any, Tuple
from github import Github, Auth

"""
pr_analyzer.py (versão LLM-driven sem regras estáticas)
------------------------------------------------------
Fluxo:
1. Coleta patch do PR (diff em formato unificado).
2. Envia patch ao Azure OpenAI com prompt para gerar JSON de sugestões.
3. Valida JSON e filtra sugestões que correspondem a linhas adicionadas.
4. Publica:
   - Comentário principal (resumo + tabela de sugestões).
   - Review com comentários inline contendo blocos ```suggestion.
Config via variáveis de ambiente:
  AZURE_OPENAI_ENDPOINT (obrigatório)
  AZURE_OPENAI_API_KEY (obrigatório)
  AZURE_OPENAI_DEPLOYMENT_NAME (default: gpt-4o)
  AZURE_OPENAI_API_VERSION (default: 2024-10-21)
  MAX_PATCH_CHARS (default: 120000)
  MAX_SUGGESTIONS (default: 15)
  ALLOW_MULTI_LINE (default: false)
  OPENAI_TEMPERATURE (default: 0.2)
  ENABLE_INLINE_SUGGESTIONS (default: true)
  COMMENT_TAG (default: azure-openai-pr-review)
"""

# -------------------------------
# Diff / Patch Collection
# -------------------------------
def get_pr_and_patch(repo_fullname: str, pr_number: int, gh_token: str):
    g = Github(auth=Auth.Token(gh_token))
    repo = g.get_repo(repo_fullname)
    pr = repo.get_pull(pr_number)

    patch_text = ""
    files_meta = []
    for f in pr.get_files():
        if f.patch:
            patch_text += f"\n### {f.filename}\n```diff\n{f.patch}\n```\n"
            files_meta.append({
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions
            })

    max_chars = int(os.environ.get("MAX_PATCH_CHARS", "120000"))
    truncated = False
    if len(patch_text) > max_chars:
        patch_text = patch_text[:max_chars] + "\n\n[TRUNCATED]"
        truncated = True

    return pr, repo, patch_text.strip(), files_meta, truncated

# -------------------------------
# OpenAI Call (JSON suggestions)
# -------------------------------
def call_llm_for_suggestions(patch: str, truncated: bool) -> Dict[str, Any]:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    max_suggestions = int(os.environ.get("MAX_SUGGESTIONS", "15"))
    allow_multi_line = os.environ.get("ALLOW_MULTI_LINE", "false").lower() == "true"

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    print(f"[DEBUG] Calling Azure OpenAI: deployment={deployment} api_version={api_version}")

trunc_note = "Patch truncado; limite sua análise a apenas a parte exibida." if truncated else "Sem truncamento."

    # Prompt: instruções rígidas para produzir JSON.
    user_prompt = f"""
Você é um revisor sênior de código C#/.NET. Gere melhorias concretas.

REQUISITOS:
- Analise APENAS o patch fornecido.
- NÃO invente arquivos ou trechos inexistentes.
- Gere no máximo {max_suggestions} sugestões.
- Cada sugestão deve focar em benefício claro (bug, segurança, performance, legibilidade, SOLID, testabilidade).
- NÃO sugerir renomeações cosméticas sem ganho real.
- Para cada sugestão defina: id único curto (S001...), file, severity (low|medium|high), type (improvement|bug|security|performance|readability|testability), categories (array), original (array de 1..N linhas exatamente como aparecem no patch sem prefixo '+'), replacement (array do mesmo tamanho), rationale (breve e objetiva).
- Se {allow_multi_line} estiver ativo, você pode usar várias linhas contíguas. Caso contrário, limite a 1 linha por sugestão.
- Todas as linhas em 'original' DEVEM ser linhas ADICIONADAS no diff (iniciadas com '+', sem o '+'). Não use linhas de contexto.
- Mantenha a lógica funcional; não remova comportamento sem justificativa.
- Não inclua imports/usings não necessários.
- Se não houver melhorias relevantes, retorne suggestions: [].

SAÍDA:
Retorne EXCLUSIVAMENTE um JSON com esta estrutura:
{{
  "summary": "string",
  "verdict": "OK|Needs Work|Blocker",
  "suggestions": [
    {{
      "id": "S001",
      "file": "caminho/Arquivo.cs",
      "severity": "low|medium|high",
      "type": "improvement|bug|security|performance|readability|testability",
      "categories": ["CleanCode","SOLID"],
      "original": ["linha exata"],
      "replacement": ["linha substituída"],
      "rationale": "Explicação objetiva"
    }}
  ]
}}

NÃO escreva texto fora do JSON.
{trunc_note}

PATCH:
{patch}
"""

    body = {
        "messages": [
            {"role": "system", "content": "Você é um revisor de código automatizado especializado em C# e arquitetura .NET. Responda somente com JSON válido."},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "0.2")),
        "response_format": {"type": "json_object"}  # caso API suporte JSON mode
    }

    headers = {"Content-Type": "application/json", "api-key": api_key}

    res = requests.post(url, headers=headers, json=body, timeout=180)
    if not res.ok:
        raise RuntimeError(f"Azure OpenAI request failed: {res.status_code} {res.text}")

    data = res.json()
    raw = None
    if "choices" in data:
        raw = data["choices"][0]["message"]["content"]
    elif "output" in data:
        # fallback hipotético
        raw = json.dumps(data["output"], ensure_ascii=False)
    else:
        raw = json.dumps(data, ensure_ascii=False)

    parsed = extract_first_json(raw)
    return parsed

def extract_first_json(text: str) -> Dict[str, Any]:
    """
    Tenta extrair o primeiro objeto JSON válido do texto.
    Se falhar, retorna estrutura fallback.
    """
    text = text.strip()
    # Se já começa com { tenta direto
    if text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            pass

    # Busca bloco JSON entre chaves balanceadas (simples)
    first_open = text.find('{')
    last_close = text.rfind('}')
    if first_open != -1 and last_close != -1 and last_close > first_open:
        candidate = text[first_open:last_close+1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return {
        "summary": "Falha ao parsear JSON retornado pelo modelo.",
        "verdict": "Needs Work",
        "suggestions": []
    }

# -------------------------------
# Diff Parsing Helpers
# -------------------------------
def build_added_lines_index(patch: str) -> Dict[str, Dict[int, str]]:
    """
    Retorna: { filename: { new_line_number: line_content } } (apenas linhas adicionadas)
    Também vamos querer uma lista ordenada para mapear sequências.
    """
    result: Dict[str, Dict[int, str]] = {}
    current_file = None
    inside = False
    new_line_no = None

    for raw in patch.splitlines():
        line = raw.rstrip('\n')

        if line.startswith("### "):
            current_file = line[4:].strip()
            result[current_file] = {}
            continue
        if line.startswith("```diff"):
            inside = True
            continue
        if line.startswith("```") and inside:
            inside = False
            current_file = None
            new_line_no = None
            continue
        if not inside or current_file is None:
            continue

        # Cabeçalho de hunk
        if line.startswith('@@'):
            m = re.search(r"\+(\d+)", line)
            if m:
                new_line_no = int(m.group(1))
            continue
        if new_line_no is None:
            continue

        if line.startswith('+') and not line.startswith('+++'):
            content = line[1:]
            result[current_file][new_line_no] = content
            new_line_no += 1
        elif line.startswith('-') and not line.startswith('---'):
            # removida: não afeta new_line_no
            continue
        else:
            # contexto: incrementa
            new_line_no += 1
    return result

def invert_added_index(added_index: Dict[str, Dict[int, str]]) -> Dict[str, List[Tuple[int, str]]]:
    """
    Para cada arquivo: retorna lista ordenada por line_number de (line_number, content).
    Facilita busca de sequências contíguas.
    """
    inv = {}
    for f, mapping in added_index.items():
        ordered = sorted(mapping.items(), key=lambda x: x[0])
        inv[f] = ordered
    return inv

# -------------------------------
# Suggestion Validation
# -------------------------------
def validate_and_localize_suggestions(model_data: Dict[str, Any],
                                      added_index: Dict[str, Dict[int, str]],
                                      allow_multi_line: bool) -> List[Dict[str, Any]]:
    """
    Filtra sugestões para garantir que cada 'original' exista nas linhas adicionadas.
    Retorna sugestões enriquecidas com line_number (início) para inline comment.
    Multi-linha: exige que as linhas existam contiguamente (line_number consecutivos).
    """
    suggestions = model_data.get("suggestions") or []
    if not isinstance(suggestions, list):
        return []

    validated = []
    for s in suggestions:
        try:
            file = s["file"]
            original_lines = s["original"]
            replacement = s["replacement"]
            if (not isinstance(original_lines, list) or
                not isinstance(replacement, list) or
                len(original_lines) == 0 or
                len(original_lines) != len(replacement)):
                continue
            if file not in added_index:
                continue

            # Buscar correspondência
            file_lines_map = added_index[file]  # line_number -> content
            match_start = find_sequence_in_added(file_lines_map, original_lines, allow_multi_line)
            if match_start is None:
                continue

            # Anexa info
            s["_line_start"] = match_start
            s["_line_end"] = match_start + len(original_lines) - 1
            validated.append(s)
        except Exception:
            continue
    return validated

def find_sequence_in_added(file_lines_map: Dict[int, str],
                           original_lines: List[str],
                           allow_multi_line: bool) -> int or None:
    """
    Se allow_multi_line = False => original_lines deve ter tamanho 1 e existir exata.
    Se True => todas as linhas devem existir de forma contígua.
    """
    if not allow_multi_line and len(original_lines) > 1:
        return None

    # Index rápido por conteúdo para single-line otimizado
    if len(original_lines) == 1:
        target = original_lines[0].strip()
        for ln, content in file_lines_map.items():
            if content.strip() == target:
                return ln
        return None

    # Multi-linha contígua
    # Estratégia: procurar primeira linha; verificar sequência
    first = original_lines[0].strip()
    candidates = [ln for ln, content in file_lines_map.items() if content.strip() == first]
    for start_ln in candidates:
        ok = True
        for offset, line_text in enumerate(original_lines):
            ln = start_ln + offset
            content = file_lines_map.get(ln)
            if content is None or content.strip() != line_text.strip():
                ok = False
                break
        if ok:
            return start_ln
    return None

# -------------------------------
# Comment + Review Generation
# -------------------------------
def build_main_comment(model_data: Dict[str, Any], validated: List[Dict[str, Any]], marker: str) -> str:
    summary = model_data.get("summary", "(sem resumo)")
    verdict = model_data.get("verdict", "Needs Work")

    table_rows = []
    if validated:
        table_rows.append("| ID | Arquivo | Severidade | Tipo | Linhas | Resumo |")
        table_rows.append("|----|---------|------------|------|--------|--------|")
        for s in validated:
            table_rows.append(
                f"| {s.get('id','?')} | {s.get('file','?')} | {s.get('severity','?')} | {s.get('type','?')} | "
                f"{s.get('_line_start')}..{s.get('_line_end')} | {truncate(s.get('rationale',''), 80)} |"
            )
    else:
        table_rows.append("_Nenhuma sugestão validada com base no diff._")

    comment = (
        f"<!-- {marker} -->\n\n"
        f"**Análise Automatizada (LLM)**\n\n"
        f"**Resumo:** {summary}\n\n"
        f"**Veredito:** {verdict}\n\n"
        f"### Sugestões Validadas\n{chr(10).join(table_rows)}\n\n"
        f"_Cada sugestão inline pode ser aplicada manualmente via 'Apply suggestion'._"
    )
    return comment

def truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len-3] + "..."

def upsert_main_comment(pr, body: str, marker: str):
    existing = None
    for c in pr.get_issue_comments():
        if c.body and c.body.startswith(f"<!-- {marker}"):
            existing = c
            break
    if existing:
        existing.edit(body)
    else:
        pr.create_issue_comment(body)

def create_inline_review(pr, validated: List[Dict[str, Any]], allow_multi_line: bool):
    if not validated:
        print("Nenhuma sugestão validada para comentários inline.")
        return

    comments_payload = []
    for s in validated:
        file = s["file"]
        line_start = s["_line_start"]
        line_end = s["_line_end"]
        original = s["original"]
        replacement = s["replacement"]
        rationale = s.get("rationale", "")
        sid = s.get("id", "")
        severity = s.get("severity", "")
        stype = s.get("type", "")

        # Construir bloco suggestion:
        # Para multiline: lines concatenadas
        replacement_text = "\n".join(replacement)
        suggestion_block = f"```suggestion\n{replacement_text}\n```"

        header = f"{sid} ({severity}/{stype})"
        body = (
            f"{header}\n\n"
            f"{rationale}\n\n"
            f"{suggestion_block}"
        )

        # Para multi-linha, a API de review aceita start_line/line (para lado direito do diff)
        if allow_multi_line and line_end > line_start:
            comments_payload.append({
                "path": file,
                "body": body,
                "start_line": line_start,
                "line": line_end,
                "side": "RIGHT",
                "start_side": "RIGHT"
            })
        else:
            comments_payload.append({
                "path": file,
                "body": body,
                "line": line_start,
                "side": "RIGHT"
            })

    if not comments_payload:
        print("Payload vazio após processamento – nada a publicar.")
        return

    try:
        pr.create_review(event="COMMENT",
                         body="Sugestões automáticas (geradas por LLM).",
                         comments=comments_payload)
        print("Review com sugestões criado.")
    except Exception as e:
        print(f"Falha ao criar review com multiline (se aplicável): {e}")
        # Fallback: remover campos multiline
        fallback = []
        for c in comments_payload:
            if "start_line" in c:
                fallback.append({
                    "path": c["path"],
                    "body": c["body"],
                    "line": c["line"],
                    "side": "RIGHT"
                })
            else:
                fallback.append(c)
        if fallback:
            try:
                pr.create_review(event="COMMENT",
                                 body="Sugestões automáticas (fallback).",
                                 comments=fallback)
                print("Review fallback criado.")
            except Exception as e2:
                print(f"Falha no fallback de review: {e2}")

# -------------------------------
# Main
# -------------------------------
def main():
    repo_fullname = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])
    gh_token = os.environ["GITHUB_TOKEN"]
    marker = os.environ.get("COMMENT_TAG", "azure-openai-pr-review")
    enable_inline = os.environ.get("ENABLE_INLINE_SUGGESTIONS", "true").lower() == "true"
    allow_multi_line = os.environ.get("ALLOW_MULTI_LINE", "false").lower() == "true"

    print(f"🔍 Analisando PR #{pr_number} em {repo_fullname} (multi-line={allow_multi_line}) ...")

    pr, repo, patch, files_meta, truncated = get_pr_and_patch(repo_fullname, pr_number, gh_token)
    if not patch:
        print("⚠️ Patch vazio.")
        return

    try:
        model_data = call_llm_for_suggestions(patch, truncated)
    except Exception as e:
        print(f"Erro na chamada ao LLM: {e}")
        model_data = {"summary": f"Falha LLM: {e}", "verdict": "Needs Work", "suggestions": []}

    added_index = build_added_lines_index(patch)
    validated = validate_and_localize_suggestions(model_data, added_index, allow_multi_line=allow_multi_line)

    comment_body = build_main_comment(model_data, validated, marker)
    upsert_main_comment(pr, comment_body, marker)

    if enable_inline and not truncated:
        create_inline_review(pr, validated, allow_multi_line)
    elif truncated:
        print("Patch truncado — não gerando sugestões inline para evitar inconsistências.")

print("✅ Análise concluída com sucesso.")

if __name__ == "__main__":
    main()

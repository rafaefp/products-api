#!/usr/bin/env python3
import os
import re
import json
import requests
import textwrap
from typing import List, Dict, Any
from github import Github, Auth

"""
pr_analyzer.py (LLM-driven) - ignora sempre o próprio arquivo.

Fluxo:
1. Coleta diff (patch) dos arquivos modificados do PR, EXCETO sempre .github/scripts/pr_analyzer.py
2. Envia patch ao Azure OpenAI com instruções para retornar JSON estruturado.
3. Valida cada sugestão (todas as linhas originais devem existir como linhas adicionadas no diff).
4. Publica/atualiza comentário principal + cria review com comentários inline (blocos `suggestion`).
5. Se só o pr_analyzer.py foi alterado, encerra sem comentar.

Config obrigatória:
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_API_KEY
O restante possui defaults:
  AZURE_OPENAI_DEPLOYMENT_NAME (default: gpt-4o)
  AZURE_OPENAI_API_VERSION (default: 2024-10-21)
  MAX_PATCH_CHARS (default: 120000)
  MAX_SUGGESTIONS (default: 15)
  ALLOW_MULTI_LINE (default: false)
  OPENAI_TEMPERATURE (default: 0.2)
  ENABLE_INLINE_SUGGESTIONS (default: true)
  COMMENT_TAG (default: azure-openai-pr-review)
"""

# Arquivos sempre ignorados (pode expandir se necessário)
EXCLUDED_ALWAYS = {".github/scripts/pr_analyzer.py"}

# --------------------------------------------------
# Patch / PR
# --------------------------------------------------
def get_pr_and_patch(repo_fullname: str, pr_number: int, gh_token: str):
    g = Github(auth=Auth.Token(gh_token))
    repo = g.get_repo(repo_fullname)
    pr = repo.get_pull(pr_number)

    patch_text = ""
    files_meta = []
    for f in pr.get_files():
        if f.filename in EXCLUDED_ALWAYS:
            print(f"[INFO] Ignorando arquivo sempre excluído: {f.filename}")
            continue
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

# --------------------------------------------------
# LLM Call
# --------------------------------------------------
def call_llm_for_suggestions(patch: str, truncated: bool) -> Dict[str, Any]:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    max_suggestions = int(os.environ.get("MAX_SUGGESTIONS", "15"))
    allow_multi_line = os.environ.get("ALLOW_MULTI_LINE", "false").lower() == "true"

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    print(f"[DEBUG] Azure OpenAI: deployment={deployment} api_version={api_version}")

    trunc_note = "PATCH TRUNCADO — limite a análise ao conteúdo visível." if truncated else ""

    raw_prompt = f"""
    Você é um revisor sênior de código C#/.NET. Gere melhorias concretas.

    REQUISITOS:
    - Analise APENAS o patch fornecido.
    - NÃO invente arquivos ou trechos inexistentes.
    - Gere no máximo {max_suggestions} sugestões.
    - Cada sugestão deve focar em benefício claro (bug, segurança, performance, legibilidade, SOLID, testabilidade).
    - Não sugerir renomeações cosméticas sem ganho técnico real.
    - Para cada sugestão definir:
        id (S001, S002...),
        file,
        severity (low|medium|high),
        type (improvement|bug|security|performance|readability|testability),
        categories (array),
        original (array de 1..N linhas adicionadas exatamente como aparecem no patch sem o '+'),
        replacement (array do mesmo tamanho),
        rationale (explicação objetiva).
    - allow_multi_line={allow_multi_line}; se false, apenas 1 linha por sugestão.
    - Linhas em 'original' DEVEM ser linhas ADICIONADAS (prefixo '+', mas sem incluir o '+').
    - Mantenha a lógica; não remova comportamento sem justificar.
    - Se não houver melhorias relevantes, retorne suggestions: [].

    SAÍDA JSON EXATA (sem texto fora do JSON):
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

    {trunc_note}

    PATCH:
    {patch}
    """
    user_prompt = textwrap.dedent(raw_prompt).strip()

    body = {
        "messages": [
            {
                "role": "system",
                "content": "Você é um revisor de código automatizado especializado em C# e arquitetura .NET. Responda apenas com JSON válido."
            },
            {"role": "user", "content": user_prompt}
        ],
        "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "0.2")),
        "response_format": {"type": "json_object"}
    }

    headers = {"Content-Type": "application/json", "api-key": api_key}
    res = requests.post(url, headers=headers, json=body, timeout=180)
    if not res.ok:
        raise RuntimeError(f"Azure OpenAI request failed: {res.status_code} {res.text}")

    data = res.json()
    raw_content = None
    if "choices" in data and data["choices"]:
        raw_content = data["choices"][0]["message"]["content"]
    elif "output" in data:
        raw_content = json.dumps(data["output"], ensure_ascii=False)
    else:
        raw_content = json.dumps(data, ensure_ascii=False)

    parsed = extract_first_json(raw_content)
    return parsed

def extract_first_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith('{'):
        try:
            return json.loads(text)
        except Exception:
            pass
    first = text.find('{')
    last = text.rfind('}')
    if first != -1 and last != -1 and last > first:
        snippet = text[first:last+1]
        try:
            return json.loads(snippet)
        except Exception:
            pass
    return {
        "summary": "Falha ao interpretar JSON do modelo.",
        "verdict": "Needs Work",
        "suggestions": []
    }

# --------------------------------------------------
# Diff parsing & validation
# --------------------------------------------------
def build_added_lines_index(patch: str) -> Dict[str, Dict[int, str]]:
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
            continue
        else:
            new_line_no += 1

    return result

def validate_and_localize_suggestions(model_data: Dict[str, Any],
                                      added_index: Dict[str, Dict[int, str]],
                                      allow_multi_line: bool) -> List[Dict[str, Any]]:
    suggestions = model_data.get("suggestions") or []
    if not isinstance(suggestions, list):
        return []

    validated = []
    for s in suggestions:
        try:
            file = s["file"]
            original_lines = s["original"]
            replacement = s["replacement"]
            if (not isinstance(original_lines, list)
                or not isinstance(replacement, list)
                or len(original_lines) == 0
                or len(original_lines) != len(replacement)):
                continue
            if file not in added_index:
                continue
            if not allow_multi_line and len(original_lines) > 1:
                continue
            match_start = find_sequence_in_added(added_index[file], original_lines)
            if match_start is None:
                continue
            s["_line_start"] = match_start
            s["_line_end"] = match_start + len(original_lines) - 1
            validated.append(s)
        except Exception:
            continue
    return validated

def find_sequence_in_added(file_lines_map: Dict[int, str], original_lines: List[str]) -> int or None:
    if len(original_lines) == 1:
        target = original_lines[0].strip()
        for ln, content in file_lines_map.items():
            if content.strip() == target:
                return ln
        return None
    first = original_lines[0].strip()
    candidates = [ln for ln, c in file_lines_map.items() if c.strip() == first]
    for start_ln in candidates:
        ok = True
        for offset, expected in enumerate(original_lines):
            ln = start_ln + offset
            if file_lines_map.get(ln, "").strip() != expected.strip():
                ok = False
                break
        if ok:
            return start_ln
    return None

# --------------------------------------------------
# Output (comment + review)
# --------------------------------------------------
def build_main_comment(model_data: Dict[str, Any], validated: List[Dict[str, Any]], marker: str) -> str:
    summary = model_data.get("summary", "(sem resumo)")
    verdict = model_data.get("verdict", "Needs Work")

    lines = []
    if validated:
        lines.append("| ID | Arquivo | Sev | Tipo | Linhas | Resumo |")
        lines.append("|----|---------|-----|------|--------|--------|")
        for s in validated:
            lines.append(
                f"| {s.get('id','?')} | {s.get('file','?')} | {s.get('severity','?')} | {s.get('type','?')} | "
                f"{s.get('_line_start')}..{s.get('_line_end')} | {truncate(s.get('rationale',''), 70)} |"
            )
    else:
        lines.append("_Nenhuma sugestão validada._")

    table = "\n".join(lines)

    return (
        f"<!-- {marker} -->\n\n"
        f"**Análise Automatizada (LLM)**\n\n"
        f"**Resumo:** {summary}\n\n"
        f"**Veredito:** {verdict}\n\n"
        f"### Sugestões\n{table}\n\n"
        f"_Aplique individualmente via 'Apply suggestion' nos comentários inline._"
    )

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
        print("Nenhuma sugestão validada para inline.")
        return

    comments_payload = []
    for s in validated:
        file = s["file"]
        line_start = s["_line_start"]
        line_end = s["_line_end"]
        replacement_lines = s["replacement"]
        rationale = s.get("rationale", "")
        sid = s.get("id", "")
        severity = s.get("severity", "")
        stype = s.get("type", "")

        replacement_text = "\n".join(replacement_lines)
        suggestion_block = f"```suggestion\n{replacement_text}\n```"
        header = f"{sid} ({severity}/{stype})"
        body = f"{header}\n\n{rationale}\n\n{suggestion_block}"

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
        print("Payload vazio após preparar comentários.")
        return

    try:
        pr.create_review(
            event="COMMENT",
            body="Sugestões automáticas (LLM).",
            comments=comments_payload
        )
        print("Review com sugestões criado.")
    except Exception as e:
        print(f"Falha ao criar review (multi-line?). Tentando fallback. Erro: {e}")
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
                pr.create_review(
                    event="COMMENT",
                    body="Sugestões automáticas (fallback).",
                    comments=fallback
                )
                print("Review fallback criado.")
            except Exception as e2:
                print(f"Falha no fallback: {e2}")

# --------------------------------------------------
# Main
# --------------------------------------------------
def main():
    repo_fullname = os.environ["GITHUB_REPOSITORY"]
    pr_number = int(os.environ["PR_NUMBER"])
    gh_token = os.environ["GITHUB_TOKEN"]
    marker = os.environ.get("COMMENT_TAG", "azure-openai-pr-review")
    enable_inline = os.environ.get("ENABLE_INLINE_SUGGESTIONS", "true").lower() == "true"
    allow_multi_line = os.environ.get("ALLOW_MULTI_LINE", "false").lower() == "true"

    print(f"🔍 Analisando PR #{pr_number} em {repo_fullname} (multi-line={allow_multi_line})")

    pr, repo, patch, files_meta, truncated = get_pr_and_patch(repo_fullname, pr_number, gh_token)

    if not patch:
        print("ℹ️ Nenhum patch restante (provavelmente só arquivos excluídos). Nada a comentar.")
        return

    try:
        model_data = call_llm_for_suggestions(patch, truncated)
    except Exception as e:
        print(f"Erro LLM: {e}")
        model_data = {"summary": f"Falha LLM: {e}", "verdict": "Needs Work", "suggestions": []}

    added_index = build_added_lines_index(patch)
    validated = validate_and_localize_suggestions(model_data, added_index, allow_multi_line)

    comment_body = build_main_comment(model_data, validated, marker)
    upsert_main_comment(pr, comment_body, marker)

    if enable_inline and not truncated:
        create_inline_review(pr, validated, allow_multi_line)
    elif truncated:
        print("Patch truncado — ignorando sugestões inline.")

    print("✅ Finalizado.")

if __name__ == "__main__":
    main()

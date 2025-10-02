#!/usr/bin/env python3
import os
import requests
from github import Github

def get_pr_files(repo_fullname, pr_number, gh_token):
    """Busca os patches dos arquivos alterados no PR"""
    g = Github(gh_token)
    repo = g.get_repo(repo_fullname)
    pr = repo.get_pull(pr_number)
    files = pr.get_files()
    patch_text = ""

    for f in files:
        if f.patch:
            patch_text += f"\n### {f.filename}\n```diff\n{f.patch}\n```\n"

    # limitar tamanho para evitar custo alto / erro
    max_chars = 120000
    if len(patch_text) > max_chars:
        patch_text = patch_text[:max_chars] + "\n\n[TRUNCATED]"

    return patch_text

def analyze_with_azure_openai(patch):
    """Chama o Azure OpenAI Responses API"""
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "my-gpt-deploy")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

    url = f"{endpoint}/openai/deployments/{deployment}/responses?api-version={api_version}"

    prompt = f"""
Você é um revisor de código automatizado. Analise o patch abaixo e gere:
- resumo curto (1-2 linhas),
- possíveis bugs, riscos de segurança,
- sugestões de melhoria,
- classificação final: [OK / Needs Work / Blocker].

Patch:
{patch}
"""

    body = {"input": prompt}
    headers = {"Content-Type": "application/json", "api-key": api_key}

    res = requests.post(url, headers=headers, json=body)
    if not res.ok:
        raise Exception(f"Azure OpenAI request failed: {res.status_code} {res.text}")

    data = res.json()

    review_text = ""
    if "output" in data and isinstance(data["output"], list):
        for o in data["output"]:
            if "content" in o:
                for c in o["content"]:
                    if "text" in c:
                        review_text += c["text"]
    elif "choices" in data:
        review_text = data["choices"][0]["message"]["content"]

    return review_text.strip() if review_text else str(data)

def post_comment(repo_fullname, pr_number, gh_token, review_text):
    """Cria ou atualiza comentário no PR"""
    g = Github(gh_token)
    repo = g.get_repo(repo_fullname)
    pr = repo.get_pull(pr_number)

    marker = "<!-- azure-openai-pr-review -->\n\n"
    comment_body = marker + "**Análise automatizada (Azure OpenAI)**\n\n" + review_text

    comments = pr.get_issue_comments()
    existing = None
    for c in comments:
        if c.body and c.body.startswith(marker):
            existing = c
            break

    if existing:
        existing.edit(comment_body)
    else:
        pr.create_issue_comment(comment_body)

if __name__ == "__main__":
    repo_fullname = os.environ["GITHUB_REPOSITORY"]  # ex: owner/repo
    pr_number = int(os.environ["PR_NUMBER"])
    gh_token = os.environ["GITHUB_TOKEN"]

    print(f"🔍 Analisando PR #{pr_number} em {repo_fullname}...")

    patch = get_pr_files(repo_fullname, pr_number, gh_token)
    review = analyze_with_azure_openai(patch)
    post_comment(repo_fullname, pr_number, gh_token, review)

    print("✅ Comentário postado/atualizado com sucesso!")

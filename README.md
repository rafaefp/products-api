# Products API

API simples de produtos construída em ASP.NET Core (.NET 8) com um único controlador que expõe operações CRUD em memória.  
O repositório também contém:
- Testes unitários básicos para o `ProductController`
- Workflow de build/test (.NET)
- Workflow de análise automática de Pull Requests usando Azure OpenAI

---

## Sumário
1. Visão Geral
2. Estrutura do Repositório
3. Arquitetura Atual (Minimalista)
4. Endpoints Disponíveis
5. Modelo de Dados (In-memory)
6. Como Executar Localmente
7. Testes
8. Workflows de CI
9. PR Code Analyzer (Azure OpenAI)
10. Roadmap (Sugestões Futuras — NÃO implementado)

---

## 1. Visão Geral
Uma API demonstrativa para fins de teste de GitHub Workflows e integração de análise automática de Pull Requests com Azure OpenAI.  
Não há persistência em banco, caching, autenticação ou camadas adicionais de domínio/infraestrutura.

---

## 2. Estrutura do Repositório

```
.
├── README.md
├── src
│   └── Products.API
│       ├── Program.cs
│       └── Controllers
│           └── ProductController.cs
├── tests
│   └── Products.UnitTest
│       └── Controllers
│           └── ProductControllerTests.cs
└── .github
    ├── workflows
    │   ├── dotnet.yml
    │   └── pr-analyzer.yml
    └── scripts
        └── pr_analyzer.py
```

Referências diretas:
- Program.cs: [src/Products.API/Program.cs](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/src/Products.API/Program.cs)
- ProductController: [src/Products.API/Controllers/ProductController.cs](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/src/Products.API/Controllers/ProductController.cs)
- Testes: [tests/Products.UnitTest/Controllers/ProductControllerTests.cs](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/tests/Products.UnitTest/Controllers/ProductControllerTests.cs)
- Workflow .NET: [.github/workflows/dotnet.yml](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/.github/workflows/dotnet.yml)
- Workflow PR Analyzer: [.github/workflows/pr-analyzer.yml](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/.github/workflows/pr-analyzer.yml)
- Script PR Analyzer: [.github/scripts/pr_analyzer.py](https://github.com/rafaefp/products-api/blob/ab9ed8573503e1c5dbc055cf234e26dec68f9dc8/.github/scripts/pr_analyzer.py)

---

## 3. Arquitetura Atual (Minimalista)

| Aspecto | Estado Atual |
|---------|--------------|
| Tipo de Projeto | ASP.NET Core Web API (Projeto único) |
| Camadas | Não há separação (tudo dentro de `Products.API`) |
| Persistência | Lista estática em memória dentro do controlador |
| Injeção de Dependências | Apenas serviços básicos adicionados (`Controllers`, `Swagger`) |
| Swagger | Ativado somente em ambiente Development |
| Segurança/Autenticação | Inexistente |
| Versionamento de API | Não aplicado |
| Configurações | Sem uso de `appsettings` personalizado exibido |
| Testes | Testes unitários cobrindo CRUD básico |

---

## 4. Endpoints Disponíveis

Base: `/api/product`

| Método | Rota | Descrição | Respostas Principais |
|--------|------|-----------|----------------------|
| GET | `/api/product` | Lista todos os produtos em memória | 200 OK |
| GET | `/api/product/{id}` | Retorna produto por Id | 200 OK / 404 NotFound |
| POST | `/api/product` | Cria novo produto (gera Id sequencial) | 201 Created |
| PUT | `/api/product/{id}` | Atualiza produto existente | 204 NoContent / 404 NotFound |
| DELETE | `/api/product/{id}` | Remove produto existente | 204 NoContent / 404 NotFound |

Exemplo (POST):
```json
{
  "name": "Fone",
  "price": 250
}
```

---

## 5. Modelo de Dados (In-memory)

Classe interna ao controller:
```csharp
public class Product {
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public decimal Price { get; set; }
}
```

Lista estática inicial (mock):
```csharp
[
  { Id = 1, Name = "Teclado", Price = 150 },
  { Id = 2, Name = "Mouse",   Price = 80  },
  { Id = 3, Name = "Monitor", Price = 1200 }
]
```

IDs novos: `max(Id) + 1`.

---

## 6. Como Executar Localmente

Pré-requisitos:
- .NET SDK 8.0.x

Comandos:
```bash
dotnet restore
dotnet run --project src/Products.API
```

Swagger (Development): `https://localhost:******/swagger`

---

## 7. Testes

Projeto de testes: `tests/Products.UnitTest`.

Cobertura dos cenários:
- `GetAll` retorna 3 itens iniciais
- `GetById` sucesso e NotFound
- `Create` gera ID incremental e CreatedAtAction
- `Update` sucesso e NotFound
- `Delete` sucesso e NotFound

Executar:
```bash
dotnet test
```

Reset do estado: uso de `Reflection` para reatribuir a lista estática antes de cada teste.

---

## 8. Workflows de CI

### 8.1 Workflow: .NET (`.github/workflows/dotnet.yml`)

- Nome: `.NET`
- Disparos: `push` e `pull_request` para branch `master`
- Ambiente: `ubuntu-latest`
- Etapas:
  1. Checkout do código
  2. Setup .NET 8.0.x
  3. Restore (`dotnet restore`)
  4. Build (`dotnet build --no-restore`)
  5. Test (`dotnet test --no-build --verbosity normal`)

Não há hoje:
- Publicação de artefatos
- Análise de cobertura
- Linters/formatadores
- Estratégia de cache de dependências

---

## 9. PR Code Analyzer (Azure OpenAI)

Workflow: `pr-analyzer.yml` → executa em eventos de Pull Request (`opened`, `synchronize`, `reopened`).

Script principal: `.github/scripts/pr_analyzer.py`.

### 9.1 Objetivo
Automatizar revisão inicial de código usando Azure OpenAI para gerar sugestões estruturadas e publicá-las no PR (comentário agregado e comentários inline), ajudando na qualidade e velocidade de revisão.

### 9.2 Fluxo
1. Coleta os diffs (patch) de TODOS os arquivos modificados.
2. Monta um bloco de texto com seções por arquivo:
   ```
   ### caminho/arquivo.ext
   ```diff
   (patch do git)
   ```
3. Envia esse "contexto" ao Azure OpenAI pedindo retorno em JSON estruturado (instruções internas do script — detalhes fora do trecho visível podem continuar depois da função).
4. Valida cada sugestão garantindo que as linhas referenciadas realmente existem no diff (evita alucinações).
5. Cria/atualiza comentário principal no PR e adiciona comentários inline (`suggestion` blocks) se habilitado.
6. Se somente o próprio script foi alterado, encerra sem comentar.

### 9.3 Comportamento de Truncamento
- Variável `MAX_PATCH_CHARS` (default 120000).
- Se excedido: corta e adiciona marcador final `[TRUNCATED]`.

### 9.4 Variáveis / Configurações
| Variável | Obrigatória | Default / Observação |
|----------|-------------|-----------------------|
| `AZURE_OPENAI_ENDPOINT` | Sim | — |
| `AZURE_OPENAI_API_KEY` | Sim | — |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Não | `gpt-4o` |
| `AZURE_OPENAI_API_VERSION` | Não | `2024-10-21` |
| `MAX_PATCH_CHARS` | Não | `120000` |
| `MAX_SUGGESTIONS` | Não | `15` |
| `ALLOW_MULTI_LINE` | Não | `false` |
| `OPENAI_TEMPERATURE` | Não | `0.2` |
| `ENABLE_INLINE_SUGGESTIONS` | Não | `true` |
| `COMMENT_TAG` | Não | `azure-openai-pr-review` |
| `GITHUB_TOKEN` | Sim (para PyGithub) | Fornecido automaticamente pelo GitHub Actions |
| `PR_NUMBER` | Sim (workflow injeta) | Número do PR |
| `GITHUB_REPOSITORY` | Sim | `owner/repo` |

### 9.5 Bibliotecas Usadas
- `requests` (chamada HTTP para Azure OpenAI)
- `PyGithub` (acesso a PRs, arquivos e criação de comentários)
- `json`, `re`, `textwrap`, `os` (utilidades internas)

### 9.6 Robustez e Validação
- Verificação de linhas existentes antes de sugerir.
- Controle de truncamento para evitar payloads grandes demais.

---

## 10. Roadmap (Sugestões Futuras — NÃO implementado)
- Adicionar relatório de cobertura (ex.: Coverlet + upload artifact).
- Persistência (EF Core / banco relacional).
- DTOs e separação de camadas (Domain/Application/Infrastructure).
- Health checks (`/health`).
- Middleware de exceção + resposta padronizada.
- Logging estruturado (Serilog).
- Autenticação (JWT) se necessário.
- Pipeline para publicar imagem Docker.
- Cache / versionamento de API.

---

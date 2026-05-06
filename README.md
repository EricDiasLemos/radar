# 📡 Job Radar — Eric Dias Lemos

Sistema automatizado de busca e candidatura em vagas de DevOps.
Roda 100% gratuito via GitHub Actions + GitHub Pages.

## Estrutura

```
job-radar/
├── .github/workflows/
│   ├── daily-scan.yml        # Roda seg–sex às 08h BRT
│   └── manual-apply.yml      # Candidatura avulsa pelo dashboard
├── scripts/
│   ├── main.py               # Orquestrador (entry point)
│   ├── scraper.py            # Busca vagas (Indeed/LinkedIn/Gupy/Vagas.com)
│   ├── scorer.py             # Calcula fit score 0–100
│   ├── letter_gen.py         # Gera carta via Claude API
│   └── mailer.py             # Envia email com currículo
├── data/
│   ├── jobs.json             # Banco de vagas
│   └── sent.json             # Histórico de candidaturas
├── dashboard/
│   └── index.html            # Interface (GitHub Pages)
├── assets/
│   └── curriculo.pdf         # ← Adicione seu currículo aqui
└── requirements.txt
```

## Setup — passo a passo

### 1. Fork / clone o repositório

```bash
git clone https://github.com/SEU_USUARIO/job-radar.git
cd job-radar
```

### 2. Adicione o currículo

Coloque o arquivo PDF em `assets/curriculo.pdf`.

### 3. Configure os GitHub Secrets

Vá em **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Chave da API Claude (console.anthropic.com) |
| `GMAIL_USER` | Seu email Gmail (ex: eric@gmail.com) |
| `GMAIL_APP_PASSWORD` | Senha de app do Gmail (não a senha normal) |
| `CANDIDATE_EMAIL` | Email para receber as candidaturas |

> **Como criar Gmail App Password:**
> Google Account → Segurança → Verificação em duas etapas → Senhas de app

### 4. Configure o GitHub Pages

- Settings → Pages → Source: **GitHub Actions**
- Ou: Source → Deploy from branch → `gh-pages` / `/ (root)`

### 5. Edite o dashboard

Em `dashboard/index.html`, atualize as constantes no topo do `<script>`:

```js
const GITHUB_OWNER = 'seu-usuario';   // ← seu username
const GITHUB_REPO  = 'job-radar';
```

### 6. Configure o token no dashboard

Para usar os botões "Forçar scan" e "Candidatar" no dashboard, abra o console do browser (F12) e rode:

```js
localStorage.setItem("gh_token", "ghp_SEU_PERSONAL_ACCESS_TOKEN")
```

Crie o token em: **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained**
Permissões necessárias: `Actions: write`

### 7. Faça o primeiro commit e push

```bash
git add .
git commit -m "feat: initial job radar setup"
git push
```

O workflow roda automaticamente na próxima seg–sex às 08h BRT,
ou acesse **Actions → Job Radar — Daily Scan → Run workflow** para rodar agora.

---

## Como funciona o scoring

| Critério | Peso |
|----------|------|
| Skills match | até 40 pts |
| Localização (BH/Remoto/Híbrido) | 20 pts |
| Nível (júnior/pleno) | 20 pts |
| Keywords positivas | até 10 pts |
| Salário | até 10 pts |

- **Score ≥ 70** → 🟢 Alto fit — candidatura automática
- **Score 50–69** → 🟡 Médio fit — aprovação manual no dashboard
- **Score < 50** → 🔴 Baixo fit — arquivado

Vagas com keywords negativas (Sênior 8+, Arquiteto, CTO, Mobile...) são rejeitadas automaticamente.

---

## Execução local

```bash
pip install -r requirements.txt

# Apenas scraping + scoring (sem envio de emails)
PYTHONPATH=scripts python scripts/main.py scan --no-auto-apply

# Candidatura manual para uma vaga específica
ANTHROPIC_API_KEY=... GMAIL_USER=... GMAIL_APP_PASSWORD=... \
PYTHONPATH=scripts python scripts/main.py apply <job_id>
```

---

## Fontes de vagas

- **Indeed BR** — indeed.com.br
- **LinkedIn Jobs** — API pública guest (sem login)
- **Gupy** — portal.gupy.io API
- **Vagas.com** — vagas.com.br

Rate limiting e user-agents rotativos estão configurados para evitar bloqueio.
Cada fonte tem fallback gracioso — se uma estiver indisponível, as demais continuam.

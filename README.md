# Comanda da Festa — Web App (Flask)

App em Python (Flask) com banco de dados, pra todos que abrirem o link verem
o mesmo evento e o mesmo status de pagamento.

## Rodando localmente

```bash
pip install -r requirements.txt
python app.py
```

Acesse http://localhost:5000

## Deploy gratuito (Render.com) — com banco Postgres

O Netlify não hospeda apps Python com banco de dados (só sites estáticos),
então recomendamos o **Render**, que tem um plano gratuito e é bem simples.
Esta versão já vem preparada pra usar **Postgres** (banco de verdade, que não
some quando o servidor reinicia).

### 1. Suba o projeto pro GitHub
Crie um repositório novo, arraste esta pasta (`festa-app`) e faça o commit.

### 2. Crie o banco Postgres no Render
1. No painel do Render, clique em **New +** → **PostgreSQL**
2. Dê um nome (ex: `comanda-db`), plano **Free**, e clique em **Create Database**
3. Espere ficar pronto e copie o valor de **Internal Database URL**
   (vai aparecer na página do banco)

### 3. Crie o Web Service
1. **New +** → **Web Service** → conecte o repositório do GitHub
2. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
3. Antes de criar, vá em **Environment** e adicione a variável:
   - **Key:** `DATABASE_URL`
   - **Value:** cole a Internal Database URL copiada no passo 2
4. Clique em **Create Web Service**

Em alguns minutos o Render te dá um link público, tipo
`https://comanda-da-festa.onrender.com` — esse é o link que você compartilha
com todo mundo. Qualquer pessoa que abrir vai ver os mesmos eventos e o mesmo
status de pagamento, e agora os dados ficam guardados no Postgres, não no
disco do servidor — então sobrevivem a reinícios e deploys novos.

### ⚠️ Sobre o plano gratuito do Render

No plano free, o Web Service "dorme" depois de alguns minutos sem uso e
demora uns 30-50 segundos pra acordar na primeira visita do dia. Pra festas
isso costuma ser tranquilo. O banco Postgres free do Render também expira
depois de 90 dias de inatividade da conta (basta recriar se isso acontecer,
ou considerar um plano pago se for algo recorrente e importante).

### Rodando localmente sem Postgres

Se você não configurar a variável `DATABASE_URL`, o app usa automaticamente
um arquivo SQLite local (`festa.db`) — ótimo pra testar no seu computador
antes de publicar.

## Estrutura do projeto

```
festa-app/
├── app.py              → rotas, banco de dados, geração de Pix
├── requirements.txt    → dependências
├── static/style.css    → visual "comanda de festa"
└── templates/          → páginas HTML (Jinja2)
```

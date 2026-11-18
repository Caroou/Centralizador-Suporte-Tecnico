# Arquitetura

## Componentes

- `app.py`: FastAPI, API, autenticação/autorização, criptografia, banco e integração LLM.
- `static/index.html`: estrutura e navegação.
- `static/app.js`: estado, renderização e chamadas à API.
- `static/style.css`: identidade visual e responsividade.
- `static/manifest.webmanifest`, ícones e `static/service-worker.js`: PWA. O service worker não guarda respostas de `/api/`.
- `render.yaml`: Render; `DATABASE_URL` conecta ao PostgreSQL Supabase. Sem ela, desenvolvimento local usa SQLite.

## Banco e dados sensíveis

`init_db()` cria e migra `users`, `sessions`, `login_attempts`, `tickets`, `ticket_steps`, `knowledge` e `app_seed_versions`. Compatibilidade entre SQLite e PostgreSQL deve ser mantida usando a camada de conexão em `app.py`.

Campos sensíveis usam AES-GCM com `DATA_ENCRYPTION_KEY`, mantida fora do banco. Senhas usam scrypt. Nunca versionar `.env`, chaves, bancos locais ou backups.

## Segurança e isolamento

- Rotas autenticadas dependem de `current_user`; escritas usam `authenticated_write`; operações administrativas usam `admin_user`.
- Toda consulta de chamados e dados privados deve filtrar por `owner_user_id` no servidor.
- Conhecimento geral pode ser lido por usuários autenticados; edição e exclusão requerem autorização de proprietário/admin aplicável.
- Não confiar em escopo, IDs ou papel fornecidos pelo navegador.
- Nunca enviar banco inteiro à LLM nem guardar dados da API no cache PWA.

## Ao alterar o projeto

Leia também [FLOWS.md](FLOWS.md), [AI_GUIDE.md](AI_GUIDE.md) e [README.md](README.md). Para dados novos, atualize migração/schema, modelos Pydantic, endpoints, interface e documentação. Não exponha segredos em logs ou frontend.

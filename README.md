# Centralizador de Soluções e Diagnósticos

Aplicação local em Python, FastAPI e SQLite para acompanhar chamados de notebooks e computadores desktop, conduzir diagnóstico assistido por IA e guardar os testes e desfechos validados.

## Estrutura

```text
Centralizador/
├── app.py                 # API, integração com IA, schema e acesso SQLite
├── centralizador.db       # criado automaticamente na primeira execução
├── render.yaml            # Blueprint de deploy para Render
├── .python-version        # versão do Python para builds consistentes
├── requirements.txt
├── .env.example           # modelo de configuração; copie para .env
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```

## Como executar

1. Instale Python 3.10 ou mais recente.
2. No terminal, nesta pasta, crie e ative um ambiente virtual (opcional, recomendado):

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Instale as dependências: `python -m pip install -r requirements.txt`.
4. Configure `LLM_API_KEY` no `.env`; preserve as demais configurações locais. O `.env` atual também tem uma chave `DATA_ENCRYPTION_KEY` gerada para esta instalação. Em uma instalação nova, gere uma chave com `python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` e salve o resultado como `DATA_ENCRYPTION_KEY` no `.env`. O padrão usa Gemini. Para endpoint compatível, defina `LLM_PROVIDER=openai_compatible`, `OPENAI_BASE_URL`, `OPENAI_MODEL` e a chave correspondente.
5. Inicie: `python -m uvicorn app:app --reload`.
6. Acesse [http://127.0.0.1:8000](http://127.0.0.1:8000) e crie sua conta administradora. A configuração inicial só é aceita pela máquina local.

O arquivo SQLite usa tabelas `tickets`, `ticket_steps` e `knowledge`. Na primeira inicialização desta versão, o app inclui uma coleção inicial de orientações gerais de hardware e Windows para notebooks e desktops na base geral; o marcador de versão evita duplicá-la em reinicializações. Essas referências não são contabilizadas como chamados resolvidos, e entram no contexto da IA apenas quando combinam com o sintoma. Chamados e conhecimento guardam o tipo de equipamento; bancos existentes recebem as novas colunas automaticamente e registros antigos permanecem classificados como notebook. A orientação mais recente gerada pela IA fica salva e criptografada no próprio chamado: reabri-lo mostra a mesma orientação, sem gerar a primeira resposta outra vez. Ao registrar o resultado de um teste, o app pede o próximo passo e substitui a orientação salva. Casos anteriores são limitados ao mesmo tipo de equipamento. O histórico enviado à IA contém apenas o estado do chamado ativo, até 12 etapas recentes, no máximo cinco casos encerrados semelhantes e até quatro referências gerais relevantes. A busca de peça só ocorre ao clicar no botão; esta versão abre pesquisas em lojas/buscador e não coleta preço ou disponibilidade automaticamente.

## Deploy e persistência

Localmente, os dados ficam no arquivo `centralizador.db` dentro da pasta do app e sobrevivem a fechar/reiniciar o servidor. `DATABASE_PATH` permite escolher outro local. Faça cópias de segurança periódicas desse arquivo; ele está ignorado pelo Git e não deve ser enviado junto com o código.

### Render + Supabase

Em produção, `DATABASE_URL` seleciona PostgreSQL; sem essa variável, o app continua usando SQLite local. No Render, o app exige `DATABASE_URL` para não gravar por engano no sistema de arquivos temporário. O `render.yaml` configura o serviço Web gratuito, região Virginia, Python 3.14.10 e health check em `/healthz`; os dados persistem no PostgreSQL do Supabase, sem disco Render.

1. Crie um projeto Supabase e escolha uma região próxima da região Virginia do Render, se disponível.
2. No Supabase, abra **Connect** e copie a URI do **Session pooler** (porta 5432), adequada a um backend persistente do Render em rede IPv4. Não use a chave `anon`/publishable: `DATABASE_URL` é a conexão PostgreSQL privada. Guarde-a como segredo.
3. No Render, acesse **New > Blueprint**, conecte este repositório e escolha `main`. O Render lerá o `render.yaml` na raiz. Informe `DATABASE_URL`, a chave Gemini em `LLM_API_KEY` e `FALLBACK_LLM_API_KEY` (a mesma chave pode ser usada nos dois modelos), além de `BOOTSTRAP_ADMIN_USERNAME`/`BOOTSTRAP_ADMIN_PASSWORD` (mínimo de 12 caracteres).
4. O Render gera `DATA_ENCRYPTION_KEY` automaticamente. Se pretende migrar dados locais antes da primeira inicialização bem-sucedida, substitua-a pela chave do `.env` local. Guarde a chave usada em local seguro e não a altere depois: ela é necessária para descriptografar os dados.
5. Confirme o deploy. A primeira execução cria as tabelas e carrega as referências gerais no Supabase. O primeiro usuário administrador é criado a partir das variáveis `BOOTSTRAP_ADMIN_*`.

O banco SQLite local não é enviado ao Git e não é copiado automaticamente para o Supabase. A primeira execução no Supabase começa com uma conta administradora nova e a base de referências gerais; chamados e contas locais precisam de migração separada caso devam ser preservados. Nunca coloque a URI, chaves de IA, senha ou chave de criptografia no GitHub.

## Login, isolamento e criptografia

Na primeira abertura local, crie a conta administradora. Ela pode criar, desativar e excluir contas de técnicos. Ao excluir uma conta, seus chamados e registros privados são removidos; suas contribuições gerais permanecem e passam para a administração. Cada usuário pode editar apenas os próprios registros, privados ou gerais; as orientações padrão ficam sob edição exclusiva da administração. A base geral é visível a todos e qualquer usuário pode publicar nela ao encerrar um chamado. A base privada é a opção padrão.

Os campos de texto de chamados, testes, observações, causas e part numbers são criptografados com AES-GCM antes de serem gravados no SQLite local ou no PostgreSQL de produção. Senhas são armazenadas como hashes scrypt, e as sessões usam cookies `HttpOnly` e `SameSite=Strict`. A chave `DATA_ENCRYPTION_KEY` fica fora do banco no `.env` local ou no cofre de variáveis secretas do host. **Faça uma cópia segura da chave separada do banco**: sem ela, os dados criptografados não podem ser recuperados. A criptografia protege os campos armazenados; um invasor com acesso ao servidor e à chave ainda poderia descriptografar esses dados.

Ao iniciar com a nova versão, o app migra os campos antigos em texto claro para criptografia e atribui os dados existentes à primeira conta administradora criada. Faça uma cópia de segurança do banco e do `.env` antes de mover a instalação para outro computador.

## Configuração da IA

`LLM_PROVIDER=gemini` usa a API REST do Google AI Studio. Alternativamente, `LLM_PROVIDER=openai_compatible` permite um endpoint compatível com OpenAI, configurado pela URL base e nome do modelo. Para contingência, configure `FALLBACK_LLM_PROVIDER`, `FALLBACK_LLM_API_KEY` e as opções `FALLBACK_OPENAI_*` ou `FALLBACK_GEMINI_MODEL`; a reserva é chamada quando o principal retorna 429, erro temporário 5xx, timeout ou resposta inválida. Credenciais inválidas (por exemplo 401/403) são exibidas como erro sem acionar a reserva, para não mascarar problemas de configuração. `MAX_OUTPUT_TOKENS` controla o limite (a aplicação limita a 2.000) e `LLM_TIMEOUT_SECONDS` ajusta o tempo máximo de espera (15 a 300 segundos; padrão 120). As chaves ficam apenas no backend, no arquivo local `.env`, ignorado pelo Git. Reinicie o servidor depois de alterar esse arquivo.

# Fluxos do produto

## Login e contas

O frontend verifica setup/sessão em `/api/auth/status` e `/api/auth/me`. Sessões usam cookie HttpOnly e escritas exigem token CSRF. Cada usuário tem seus próprios chamados; administração de usuários é exclusiva de admin.

## Chamado e troubleshooting

1. Abrir chamado requer tipo, modelo e sintoma; testes previamente feitos entram como etapas.
2. Buscar no máximo cinco casos encerrados relevantes e poucas orientações gerais compatíveis.
3. Ao pedir uma orientação, enviar à LLM apenas chamado ativo, histórico recente limitado e resumos selecionados. Salvar a orientação no chamado para não gerá-la de novo ao reabrir.
4. Registrar resultado (`passou`, `falhou`, `inconclusivo`) e observação. “Passou” significa que o teste não encontrou falha, não que o sintoma cessou.
5. Perguntar se o sintoma continua antes de solicitar outro passo à IA.
6. Ao encerrar, registrar desfecho, causa/solução e escopo da base. Os dados do caso e testes alimentam a base escolhida.

## Base de conhecimento

`private` é do proprietário; `general` é visível aos usuários. Casos criados ao encerrar podem ter um resumo e várias linhas de teste agrupadas por `ticket_id`. Excluir conhecimento não deve apagar o chamado original. Registros padrão são versionados em `app_seed_versions`.

## Histórico

`GET /api/tickets?status=encerrado` retorna os chamados concluídos do usuário atual. Chamados abertos e encerrados devem permanecer em telas distintas.

## Peças

Busca de peças é sob demanda. Trate FRUs da IA como candidatos que precisam ser conferidos na etiqueta física/manual. Não inventar URLs, preços ou disponibilidade.

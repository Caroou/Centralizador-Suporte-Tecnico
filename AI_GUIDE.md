# Guia para agentes de programação

Leia [ARCHITECTURE.md](ARCHITECTURE.md), [FLOWS.md](FLOWS.md) e [README.md](README.md) antes de mudanças relevantes.

## Regras de produto

- Usar português brasileiro e manter interface simples, responsiva e azul.
- Preservar isolamento por usuário, autenticação, CSRF, criptografia e segurança das sessões.
- Não repetir testes já registrados nem disparar novo turno de IA automaticamente após salvar resultado.
- “Passou” quer dizer que o teste não detectou falha. Confirmar se o sintoma persiste.
- Recomendar troca/compra apenas após esgotar testes seguros e haver evidência; nunca pesquisar peça automaticamente em todo turno.
- Exibir 429/indisponibilidade amigavelmente, sem revelar chaves.

## IA

Prompt/parser estão em `app.py`. Contexto compacto: chamado atual, etapas recentes limitadas, até cinco casos anteriores e poucas referências gerais. Validar JSON e filtrar testes repetidos no servidor. Limitar tokens.

Configuração atual: Gemini 3.5 Flash-Lite principal e Gemini 3.1 Flash-Lite fallback. Chaves ficam nas variáveis de ambiente/Render, nunca no código. A mesma chave pode significar cota compartilhada.

## Persistência e conclusão

Manter SQLite local e PostgreSQL Supabase. Escritas devem validar proprietário no backend e criptografar campos sensíveis. Não cachear respostas da API ou conteúdo privado no service worker. Atualize esta documentação quando os fluxos mudarem e relate apenas verificações realmente feitas.

# Instruções — refinamento manual (via Claude Code, sem API)

Repositório: /home/livim/jobs/liko/transcript — projeto `projects/vila-verde/`.

1. Leia `prompts/refine.md`: as regras entre `<!-- SYSTEM:START -->` e `<!-- SYSTEM:END -->` são o seu guia de edição
   (ignore a parte de `<glossario>` e `<contexto_anterior>`: você processa a aula inteira de uma vez).
2. Leia o PADRÃO DE REFERÊNCIA aprovado pelo usuário e imite o nível de limpeza, estrutura e tom:
   - entrada: `projects/vila-verde/4_markdown/metodo/mindset/3-labia-x-metodo-comunidade-vilaverde.md`
   - saída aprovada: `projects/vila-verde/5_refined/metodo/mindset/3-labia-x-metodo-comunidade-vilaverde.md`
3. Para cada aula do seu lote (`<slug>`):
   - Entrada: `projects/vila-verde/4_markdown/<slug>.md`; se não existir, leia em ordem todos os
     `projects/vila-verde/4_markdown/<slug>/parte-*.md` (ignore `index.md`) como um texto único.
   - Saída: `projects/vila-verde/5_refined/<slug>.md` (um arquivo por aula, crie as pastas). Mesmo front matter da entrada,
     trocando `type: transcricao-refinada` e acrescentando `refined_by: claude-opus-5-5 (Claude Code, manual)` e
     `source_markdown: <nome do arquivo de entrada>.md`.
   - Títulos `##`/`###` por tema com o `[mm:ss]` do trecho; listas só quando há enumeração real; negrito com moderação.
   - **NÃO resuma, NÃO corte conteúdo.** Remova só ruído da fala. Corrija erros de reconhecimento pelo contexto.
     Mantenha propaganda/menções a produtos (ex.: Chat Date), palavrões e o tom do falante (Murilo).
   - Aulas longas: escreva a saída em várias etapas (Write da primeira metade e depois Edit/append), garantindo que
     o arquivo final cobre a aula INTEIRA até o último timestamp da entrada. Confira o último `[mm:ss]` no fim.
   - Termine e grave cada aula antes de começar a próxima.
4. Não altere nenhum outro arquivo (nem `state.json`, nem `4_markdown/`).
5. Ao final, reporte: para cada aula, OK/erro, e nomes/termos dos quais você ficou em dúvida sobre a grafia.

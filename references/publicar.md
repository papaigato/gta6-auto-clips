# Postar no TikTok (opcional)

Posta pelo TikTok Studio num navegador automático (Playwright), usando o cookie de sessão. Os seletores dependem da interface do TikTok, que muda: se falhar, o script salva um print em `~/clipper-gta6/tiktok_debug/` e diz em que etapa parou.

**Sempre confirme com o usuário antes de `run` sem `--dry-run`.** Mostre a lista (`clip tiktok list`) e o `--dry-run` antes.

## Configurar (uma vez)

1. `clip tiktok instalar` (playwright + chromium no ambiente do clipper).
2. Exporte os cookies do tiktok.com logado (extensão "Get cookies.txt", formato Netscape ou JSON).
3. Guarde fora de pasta compartilhada e aponte a variável:
   - Mac/Linux: `chmod 600 ~/tiktok_cookies.txt` e `export CLIPPER_COOKIES_TIKTOK=~/tiktok_cookies.txt`
   - Windows: `$env:CLIPPER_COOKIES_TIKTOK = "$HOME\tiktok_cookies.txt"`

O `sessionid` dá acesso total à conta: nunca mostre o valor no chat. Se vazar, saia da conta no TikTok.

## Usar

| Objetivo | Comando |
|---|---|
| Pôr todos os cortes de uma live na fila (legenda = `.txt` do corte) | `clip tiktok add-live <NOME>` |
| Pôr um vídeo na fila | `clip tiktok add <VIDEO> "<LEGENDA>"` |
| Ver a fila | `clip tiktok list` |
| Simular | `clip tiktok run --dry-run` |
| Postar (3–5 por dia, 45–90 min entre posts) | `clip tiktok run --max-dia 5` |
| Congelar a fila (vídeos travados em 0 views) | `clip tiktok run --pausar 36` |

`run` espera o intervalo entre um post e outro, então demora horas: rode em segundo plano (`nohup clip tiktok run > fila.log 2>&1 &` no Mac/Linux). Itens já postados nunca são reenviados.

Não automatize curtida, comentário nem follow. Mantenha o crédito da live na legenda.

---
name: clipper-gta6
description: Transforma lives (YouTube, Twitch, Kick) e vídeos longos do YouTube (podcast, aula) em cortes verticais 9:16 para Reels, TikTok e Shorts, com câmera do streamer em cima e jogo embaixo, legenda palavra por palavra, título-gancho e texto do post com hashtags. Também acha as maiores lives de GTA 6 do dia e posta no TikTok com fila anti-spam. Use quando o usuário pedir cortes, clipes, clipper, cortar live ou vídeo, Reels/Shorts/TikTok de uma live, cortes de GTA 6, ou postar cortes no TikTok.
---

# Clipper de cortes virais

## Como rodar o motor

- Mac/Linux: `~/clipper-gta6/clip <comando>`
- Windows (PowerShell): `& "$HOME\clipper-gta6\clip.cmd" <comando>`

Se o atalho não existir, instale: `curl -fsSL https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/instalar.sh | bash` (Windows: `irm https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/instalar.ps1 | iex`). Espere aparecer **TUDO PRONTO**.

**AINDA TRABALHANDO [XX%] não é erro.** O trabalho segue em segundo plano: rode o mesmo comando de novo até terminar. Nada recomeça.

| Objetivo | Comando |
|---|---|
| Achar as maiores lives de GTA 6 de hoje | `clip buscar --quantas 7` |
| 1. Baixar o áudio, transcrever e achar trechos quentes | `clip preparar <LINK>` (`--idioma es` se não for pt/en) |
| 1b. Vídeo com capítulos: capítulos viram momentos | `clip capitulos <NOME>` |
| 2. Ficar com os melhores | `clip escolher <NOME> --manter 3 [--perfil impacto\|explicativo\|livre]` |
| 3. Renderizar | `clip fazer <NOME> --estilo auto\|split\|blur\|preencher` |
| Tudo sozinho (IA fraca ou com pressa) | `clip automatico <LINK> --quantos 3` |
| Status | `clip status` |
| Postar no TikTok | `clip tiktok ...` (ler `references/publicar.md`) |

## Fluxo

1. **Preparar.** `clip preparar <LINK>` (live precisa ter terminado). Gera na pasta da live:
   - `candidatos.txt`: os trechos mais quentes, com `[ALTO +12dB]` (grito) e `[CHAT 3.1x]` (chat acelerou);
   - `blocos/bloco_NN.txt`: a transcrição inteira em blocos de 12 min.
2. **Escolher os momentos (sua parte).** Leia `references/avaliacao.md` e escreva `momentos/candidatos.json`.
   - **Live/gameplay:** leia `candidatos.txt`. Marca não é momento: confirme pela fala. Perfil `impacto`.
   - **Vídeo comum (podcast, aula):** se tiver capítulos, `clip capitulos` e `--perfil livre`. Senão, leia `blocos/` e divida por assunto (ideia completa, faz sentido sozinha, começa numa frase que prende). Perfil `explicativo`.
   - Pontue com `criterios` (a nota sai da fórmula). Rigor antes de volume: se só achou 2 bons, diga isso e não invente.
3. `clip escolher <NOME> --manter N --perfil ...`: ordena, tira sobreposição, encaixa nos limites de frase e mostra os ajustes.
4. **Antes de `fazer`, pergunte o estilo** (a menos que o usuário já tenha dito):
   - `split`: câmera do streamer em cima, jogo embaixo (sem câmera achada, cai para `blur`);
   - `blur`: vídeo inteiro no meio, fundo desfocado (bom quando HUD ou texto da borda importa);
   - `preencher`: tela cheia, corta as laterais (`--foco 0` esquerda, `0.5` centro, `1` direita);
   - `auto` (padrão): `split` se achar câmera, senão `blur`.
5. `clip fazer <NOME> --estilo ...`. Trocar o estilo depois refaz só os cortes afetados.
6. **Entregar.** Liste cada corte com nota e caminho. Cada `corte_NN.mp4` tem um `corte_NN.txt` com título, post e crédito da live. Pergunte se quer postar.

Saída: `~/clipper-gta6/cortes/<NOME>/` (ou `CLIPPER_CORTES_DIR`; no Windows usa o Google Drive `G:\Meu Drive\GTA6_Cortes` se existir).

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `NÃO DÁ PRA BAIXAR` | trava do site (idade, membros, Kick): use outro link ou `buscar` |
| Erro de download | `clip instalar` (atualiza o baixador) e repita |
| Momento ruim | apague do JSON, rode `escolher` e `fazer` de novo |
| Bloqueio de bot do YouTube | cookies em `~/cookies.txt` ou `CLIPPER_COOKIES` |
| Câmera cortada errado | `CLIPPER_CAM_MODO=canto` (caixa fixa no canto) ou `--estilo blur` |

## Regras

- Corte só de quem permite cortes; mantenha o crédito do `.txt` no post.
- Publicar é ação externa: mostre o `--dry-run` e só poste depois do ok.
- Não automatize curtida, comentário nem follow. Não prometa viralidade.
- Cookies são credenciais: nunca mostre o conteúdo no chat.

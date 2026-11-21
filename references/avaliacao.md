# Rubrica de avaliação dos momentos

Use ao escrever `momentos/*.json`. Se o momento tiver `criterios`, o `escolher` calcula a nota sozinho pela fórmula abaixo (a `nota` escrita é ignorada). Nota < 60 é descartada.

## Critérios (0–10 cada)

| Critério | Pergunta | Peso |
|---|---|---|
| gancho | Os primeiros 1–3 s fazem parar o scroll? | 30% |
| clareza | A fala/ação se entende sozinha? | 20% |
| contexto | Faz sentido sem o resto da live? | 20% |
| interesse | Vale pra quem não conhece o streamer? | 20% |
| encerramento | Termina numa frase ou reação completa? | 10% |

Nota = `10 × (0.3·gancho + 0.2·clareza + 0.2·contexto + 0.2·interesse + 0.1·encerramento)`.
Ex.: 8, 7, 8, 8, 7 → 77. Acima de 80 é bom; 90+ qualquer pessoa para de rolar.

## Vale um corte
Primeira reação a algo do jogo, descoberta absurda, grito/susto, falha ou morte engraçada, opinião forte, história ou piada que fecha sozinha. Em vídeo comum: pergunta + resposta, história com fim, argumento com conclusão.

## Jogue fora
Precisa de contexto anterior; começa com enrolação ("é…", "então…", "voltando…"); leitura de doação, propaganda, tela de carregamento, conversa sobre a própria live; fala picada.

## Perfis (`escolher --perfil`)

| Perfil | Duração | Quando |
|---|---|---|
| `impacto` (padrão) | 20–60 s | live, gameplay, reação, humor |
| `explicativo` | 40–95 s | podcast, aula, opinião |
| `livre` | 8 s–10 min | capítulos (`clip capitulos`) |

O `escolher` encaixa início e fim no limite de frase da transcrição; mesmo assim, comece 1–2 s antes do gancho.

## Formato

```json
[
  {
    "inicio": "00:45:12",
    "fim": "00:45:55",
    "titulo": "A IA DA POLÍCIA NO GTA 6 TÁ INSANA!",
    "post": "Você acha que despistaria a polícia assim? 😱 Comenta! 👇 #gta6 #gtavi #cortes #reelsgames",
    "tipo": "fuga de 5 estrelas",
    "porque": "perseguição com viaturas capotando e streamer surtando com a física",
    "criterios": {"gancho": 9, "clareza": 9, "contexto": 8, "interesse": 9, "encerramento": 8}
  }
]
```

- `titulo`: até ~45 letras, MAIÚSCULAS em corte de impacto, sem entregar o final, na língua do vídeo.
- `post`: 1–2 frases + 4–6 hashtags. Com menos de 3, o `escolher` completa com `CLIPPER_HASHTAGS`.
- Sem `criterios`, vale a `nota` (0–100) escrita.

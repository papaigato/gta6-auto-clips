# 🎮 GTA 6 Viral Clipper

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/papaigato/gta6-auto-clips/blob/develop/GTA6_Clipper_Colab.ipynb)

Ferramenta automatizada para gerar cortes virais (Shorts, Reels, TikTok) a partir de lives e vídeos longos de GTA 6 usando Whisper, detecção facial YuNet e renderização vertical em até 2K/60fps.

---

## ⚡ Rodar no Google Colab (100% na Nuvem com GPU T4)

Você pode rodar todo o processo na nuvem com **GPU Grátis (NVIDIA T4)**, sem usar a CPU nem a memória do seu computador:

1. Clique no botão **Open in Colab** acima (ou [clique aqui](https://colab.research.google.com/github/papaigato/gta6-auto-clips/blob/develop/GTA6_Clipper_Colab.ipynb)).
2. Certifique-se de que o ambiente está configurado para **T4 GPU** (*Ambiente de execução* → *Alterar tipo de ambiente de execução* → **T4 GPU**).
3. Execute as células em ordem:
   - **📁 Célula 1:** Conecta seu Google Drive (onde os cortes prontos serão salvos).
   - **⚙️ Célula 2:** Instala dependências (FFmpeg, Whisper, CUDA 12, YuNet) e baixa o código do repositório.
   - **🎬 Célula 3:** Cole o link da live/vídeo no campo `LINK_DA_LIVE` e dê Play para gerar os vídeos!

---

## 🚀 Recursos

- **Detecção Inteligente:** Encontra os trechos mais quentes e com maior reação na live.
- **Split-Screen com Rastreamento Facial:** Detector YuNet enquadra a webcam do streamer no topo e o gameplay embaixo (layout 30/70).
- **Legendas Dinâmicas:** Transcrição precisa com Whisper e legendas animadas em alta resolução.
- **2K e 60 FPS:** Renderização fluida em até 1440x2560 para máxima qualidade no TikTok e Reels.
- **Google Drive Integrado:** Todos os cortes e metadados (`.txt` com hashtags) salvos diretamente na pasta `GTA6_Cortes`.

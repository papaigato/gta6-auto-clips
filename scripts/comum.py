"""Coisas que todos os passos do clipper usam: pastas, tempo e chamadas de programas."""
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

def obter_pasta_cortes():
    r"""Detecta automaticamente o Google Drive de 4TB (unidade G:\ ou Meu Drive) ou usa CLIPPER_CORTES_DIR."""
    if "CLIPPER_CORTES_DIR" in os.environ:
        p = Path(os.environ["CLIPPER_CORTES_DIR"])
        p.mkdir(parents=True, exist_ok=True)
        return p
    # Busca por unidades do Google Drive no Windows
    for letra in ("G", "H", "I", "D", "E", "F"):
        for sub in ("Meu Drive", "My Drive"):
            raiz = Path(f"{letra}:/{sub}")
            if raiz.exists():
                pasta_drive = raiz / "GTA6_Cortes"
                try:
                    pasta_drive.mkdir(parents=True, exist_ok=True)
                    return pasta_drive
                except OSError:
                    pass
    if Path("/content/drive/MyDrive").exists():
        p = Path("/content/drive/MyDrive/GTA6_Cortes")
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.home() / "clipper-gta6" / "cortes"

CORTES = obter_pasta_cortes()

def obter_casa():
    if "CLIPPER_GTA6_HOME" in os.environ:
        return Path(os.environ["CLIPPER_GTA6_HOME"])
    # Se rodando no Google Colab, persiste o cache de lives no Google Drive para nao perder na troca de VM / GPU
    if Path("/content/drive/MyDrive").exists():
        cache_drive = CORTES / ".cache"
        cache_drive.mkdir(parents=True, exist_ok=True)
        return cache_drive
    return Path.home() / "clipper-gta6"

CASA = obter_casa()
TRABALHO = CASA / "trabalho"   # áudio, transcrição e trechos de cada live
MODELOS = CASA / "modelos"     # o detector de rosto (baixado no setup)
YUNET = MODELOS / "face_detection_yunet_2023mar.onnx"
if not YUNET.exists() and Path("/root/clipper-gta6/modelos/face_detection_yunet_2023mar.onnx").exists():
    YUNET = Path("/root/clipper-gta6/modelos/face_detection_yunet_2023mar.onnx")
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
BLOCO_MIN = 12  # a IA lê a transcrição 12 minutos por vez


def pasta_temp_live(pasta):
    """Retorna pasta rápida em SSD local (/tmp no Colab) para arquivos pesados temporários (WAV, trechos, render).
    No PC local retorna a própria pasta da live."""
    tmp_env = os.environ.get("CLIPPER_TMP_DIR")
    if tmp_env:
        p = Path(tmp_env) / Path(pasta).name
        p.mkdir(parents=True, exist_ok=True)
        return p
    if Path("/content/drive/MyDrive").exists():
        p = Path("/tmp/clipper_gta6") / Path(pasta).name
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path(pasta)


def cuda_ld_library_path():
    """Encontra diretórios lib da NVIDIA (cublas/cudnn) instalados via pip no Linux/Colab."""
    if os.name == "nt":
        return ""
    caminhos = []
    for base in sys.path:
        nv = Path(base) / "nvidia"
        if nv.is_dir():
            for lib in nv.glob("*/lib"):
                if lib.is_dir():
                    caminhos.append(str(lib))
    return ":".join(dict.fromkeys(caminhos))


_WHISPER = {}


def carregar_whisper(modelo):
    """Carrega o modelo do faster-whisper uma vez por processo (GPU se der, senão CPU int8)."""
    from faster_whisper import WhisperModel
    disp = os.environ.get("CLIPPER_DEVICE", "auto")
    comp = os.environ.get("CLIPPER_COMPUTE_TYPE", "auto")
    if (modelo, disp, comp) not in _WHISPER:
        try:
            _WHISPER[(modelo, disp, comp)] = WhisperModel(modelo, device=disp, compute_type=comp)
        except Exception:
            _WHISPER[(modelo, disp, comp)] = WhisperModel(modelo, device="cpu", compute_type="int8")
    return _WHISPER[(modelo, disp, comp)]


PROMPT_PADRAO = os.environ.get(
    "CLIPPER_WHISPER_PROMPT",
    "GTA 6, GTA VI, Vice City, Leonida, Jason, Lucia, Rockstar, Kick, Twitch, YouTube, Super Chat, Pix, live, gameplay, streamer."
)


def transcrever_audio(modelo, audio, idioma=None, palavras=False):
    """Transcreve um array de áudio 16 kHz. Na GPU usa o modo em lote (bem mais rápido); devolve (lista, info)."""
    kw = dict(language=idioma, vad_filter=True, beam_size=1, condition_on_previous_text=False,
              word_timestamps=palavras)
    if PROMPT_PADRAO:
        kw["initial_prompt"] = PROMPT_PADRAO
    if getattr(modelo.model, "device", "cpu") == "cuda" and os.environ.get("CLIPPER_LOTE", "1") != "0":
        try:
            import inspect
            from faster_whisper import BatchedInferencePipeline
            pipe = BatchedInferencePipeline(model=modelo)
            aceitos = inspect.signature(pipe.transcribe).parameters
            kw_lote = {k: v for k, v in kw.items() if k in aceitos}
            segs, info = pipe.transcribe(
                audio, batch_size=int(os.environ.get("CLIPPER_LOTE_TAM", "16")), **kw_lote)
            return list(segs), info
        except (ImportError, TypeError):
            pass  # faster-whisper antigo: segue no modo normal
    segs, info = modelo.transcribe(audio, **kw)
    return list(segs), info


_NVENC_OK = None
_CUDA_DEC_OK = None
_SCALE_CUDA_OK = None


def tem_nvenc():
    """Testa uma única vez se o encoder de hardware NVIDIA (h264_nvenc) está disponível e funcional."""
    global _NVENC_OK
    modo = os.environ.get("CLIPPER_ENCODER", "auto").lower()
    if modo == "cpu":
        return False
    if modo == "nvenc":
        return True
    if _NVENC_OK is not None:
        return _NVENC_OK
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=15
        )
        _NVENC_OK = (r.returncode == 0)
    except Exception:
        _NVENC_OK = False
    return _NVENC_OK


def tem_cuda_decode():
    """Testa se o FFmpeg suporta decodificação CUDA (NVDEC) junto com a GPU NVIDIA."""
    global _CUDA_DEC_OK
    if os.environ.get("CLIPPER_HWDEC", "auto").lower() == "0":
        return False
    if _CUDA_DEC_OK is not None:
        return _CUDA_DEC_OK
    if not tem_nvenc():
        _CUDA_DEC_OK = False
        return False
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=10)
        _CUDA_DEC_OK = ("cuda" in r.stdout.lower())
    except Exception:
        _CUDA_DEC_OK = False
    return _CUDA_DEC_OK


def tem_scale_cuda():
    """Testa uma única vez se o filtro scale_cuda (redimensionamento na VRAM da GPU) está disponível."""
    global _SCALE_CUDA_OK
    if os.environ.get("CLIPPER_SCALE_CUDA", "auto").lower() == "0":
        return False
    if _SCALE_CUDA_OK is not None:
        return _SCALE_CUDA_OK
    if not tem_nvenc():
        _SCALE_CUDA_OK = False
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-vf", "format=nv12,hwupload_cuda,scale_cuda=128:128,hwdownload,format=nv12",
             "-f", "null", "-"],
            capture_output=True, timeout=15
        )
        _SCALE_CUDA_OK = (r.returncode == 0)
    except Exception:
        _SCALE_CUDA_OK = False
    return _SCALE_CUDA_OK


def slug(texto, limite=60):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:limite].strip("-") or "live"


def hms(seg):
    seg = max(0, int(round(seg)))
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def segundos(valor):
    """Aceita 3723, '3723', '1:02:03' ou '62:03'."""
    if isinstance(valor, (int, float)):
        return float(valor)
    partes = [float(p) for p in str(valor).strip().split(":")]
    total = 0.0
    for p in partes:
        total = total * 60 + p
    return total


def rodar(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def tem(programa):
    return shutil.which(programa) is not None


def ffmpeg_embutido():
    """Sem ffmpeg no computador, usa o ffmpeg que vem no pacote static-ffmpeg (baixado no instalar)."""
    if tem("ffmpeg") and tem("ffprobe"):
        return True
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths(weak=True)
    except Exception:
        return False
    return tem("ffmpeg") and tem("ffprobe")


def buscar_cookies():
    """Busca cookies do YouTube no Google Drive, no Colab ou configurados por variável."""
    candidatos = [
        os.environ.get("CLIPPER_COOKIES"),
        Path("/content/drive/MyDrive/cookies.txt"),
        Path("/content/drive/MyDrive/GTA6_Cortes/cookies.txt"),
        Path("/content/cookies.txt"),
        Path.home() / "cookies.txt",
    ]
    for c in candidatos:
        if c and Path(c).is_file():
            return Path(c)
    return None


def ytdlp():
    """yt-dlp do ambiente do clipper (sempre atualizado pelo setup) ou o do sistema."""
    local = Path(sys.executable).parent / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    cmd = [str(local)] if local.exists() else [sys.executable, "-m", "yt_dlp"]
    ff_dir = Path(sys.executable).parent
    if (ff_dir / "ffmpeg.exe").exists() or (ff_dir / "ffmpeg").exists():
        cmd += ["--ffmpeg-location", str(ff_dir)]
    # o YouTube está passando a exigir um JavaScript pra liberar os formatos: o instalar põe o Deno no ambiente
    deno = Path(sys.executable).parent / ("deno.exe" if os.name == "nt" else "deno")
    if deno.exists():
        cmd += ["--js-runtimes", f"deno:{deno}"]
    elif tem("deno") or tem("node"):
        cmd += ["--js-runtimes", "deno" if tem("deno") else "node"]
    
    # Cookies para evitar bloqueio de bot em nuvem (Colab)
    cookies = buscar_cookies()
    if cookies:
        cmd += ["--cookies", str(cookies)]
    return cmd


TRANCADA = ("confirm your age", "inappropriate for some users", "members-only", "join this channel",
            "subscriber", "private video", "requires authentication", "sign in to confirm")


def motivo_trancada(erro):
    """Se o yt-dlp recusou porque a live pede login (idade, membros, inscritos, privada), diz isso em português."""
    t = (erro or "").lower()
    if not any(k in t for k in TRANCADA):
        return None
    if "age" in t or "inappropriate" in t:
        return "essa live é trancada por idade (o YouTube pede login pra ver)"
    if "member" in t or "join this channel" in t or "subscriber" in t:
        return "essa live é só pra membros/inscritos do canal"
    return "essa live pede login (privada ou restrita)"


def ler_json(caminho, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho, dados):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def pasta_da_live(nome):
    """Aceita o nome da pasta, um pedaço dele ou o link original."""
    if (TRABALHO / nome).is_dir():
        return TRABALHO / nome
    for p in sorted(TRABALHO.glob("*")):
        info = ler_json(p / "info.json", {})
        if nome in (info.get("url"), info.get("webpage_url")) or nome.lower() in p.name:
            return p
    sys.exit(f"Não achei a live '{nome}' em {TRABALHO}. Rode antes: clip.py preparar LINK")

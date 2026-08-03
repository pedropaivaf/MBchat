# MB Chat - Gravacao e leitura de audio para bolhas de voz (mic estilo WhatsApp)
# Modulo isolado: so importado por gui.py, com guarda HAS_SOUNDDEVICE (mesmo
# padrao de HAS_PIL/HAS_TRAY/HAS_WINOTIFY/HAS_WINDND). Sem numpy: bytes PCM
# crus (int16 mono) sao lidos com struct.unpack manual.
import io
import struct
import threading
import wave

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (int16)


class AudioRecorder:
    def __init__(self):
        self._stream = None
        self._chunks = []
        self._lock = threading.Lock()
        self._recording = False
        self._peak_since_read = 0.0  # pico acumulado desde a ultima leitura

    def _callback(self, indata, frames, time_info, status):
        data = bytes(indata)
        with self._lock:
            self._chunks.append(data)
        try:
            count = len(data) // 2
            if count:
                peak = 0
                for i in range(0, count * 2, 2):
                    v = struct.unpack_from('<h', data, i)[0]
                    if v < 0:
                        v = -v
                    if v > peak:
                        peak = v
                # Normaliza pelo range real do int16 (nao um chute fixo).
                # Linear, sem curva perceptual — testado e a curva (raiz
                # quadrada) comprimia demais a diferenca entre trecho baixo
                # e alto (18x de diferenca real virava so ~3x na barra),
                # fazendo a onda parecer "sem seguir o volume real".
                norm = peak / 32768.0
                with self._lock:
                    if norm > self._peak_since_read:
                        self._peak_since_read = norm
        except Exception:
            pass

    # Le o pico acumulado desde a ultima leitura e reseta. Usado no polling
    # da GUI (a cada ~100ms) — evita perder picos transitorios que aconteceram
    # ENTRE duas leituras (o antigo self.level so guardava o ultimo bloco).
    def read_level(self):
        with self._lock:
            lvl = self._peak_since_read
            self._peak_since_read = 0.0
        return lvl

    def start(self):
        if not HAS_SOUNDDEVICE:
            raise RuntimeError('sounddevice indisponivel')
        self._chunks = []
        self._peak_since_read = 0.0
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16',
            callback=self._callback)
        self._stream.start()
        self._recording = True

    def stop(self):
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            data = b''.join(self._chunks)
            self._chunks = []
        return data

    def cancel(self):
        self.stop()

    @property
    def is_recording(self):
        return self._recording


# Empacota PCM cru (int16 mono) num WAV valido em memoria.
def pcm_to_wav_bytes(pcm_data, sample_rate=SAMPLE_RATE, channels=CHANNELS,
                     sample_width=SAMPLE_WIDTH):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# Duracao em segundos de um .wav (path ou bytes).
def wav_duration(wav_source):
    try:
        if isinstance(wav_source, (bytes, bytearray)):
            f = wave.open(io.BytesIO(wav_source), 'rb')
        else:
            f = wave.open(wav_source, 'rb')
        frames = f.getnframes()
        rate = f.getframerate()
        f.close()
        return frames / float(rate) if rate else 0.0
    except Exception:
        return 0.0


# Recorta um .wav (path ou bytes) a partir de start_fraction (0.0-1.0) ate o
# fim, retornando os bytes de um novo .wav valido com so esse trecho.
# winsound nao tem como "dar seek" num arquivo em reproducao — pra clicar/
# arrastar na onda e pular pra um ponto do audio, tocamos um arquivo novo so
# com o restante a partir do ponto clicado.
def trim_wav_from(wav_source, start_fraction):
    try:
        if isinstance(wav_source, (bytes, bytearray)):
            f = wave.open(io.BytesIO(wav_source), 'rb')
        else:
            f = wave.open(wav_source, 'rb')
        n_channels = f.getnchannels()
        sampwidth = f.getsampwidth()
        framerate = f.getframerate()
        n_frames = f.getnframes()
        start_frame = int(max(0.0, min(1.0, start_fraction)) * n_frames)
        f.setpos(min(start_frame, max(0, n_frames - 1)))
        remaining = f.readframes(n_frames - start_frame)
        f.close()
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.writeframes(remaining)
        return buf.getvalue()
    except Exception:
        return None


# Envelope de amplitude (lista de `bars` valores 0.0-1.0, normalizados pelo
# pico) para desenhar a onda estatica da bolha/preview. Sem numpy.
def wav_waveform(wav_source, bars=28):
    try:
        if isinstance(wav_source, (bytes, bytearray)):
            f = wave.open(io.BytesIO(wav_source), 'rb')
        else:
            f = wave.open(wav_source, 'rb')
        n_channels = f.getnchannels()
        sampwidth = f.getsampwidth()
        n_frames = f.getnframes()
        raw = f.readframes(n_frames)
        f.close()
        if sampwidth != 2 or n_frames == 0:
            return [0.3] * bars
        total_samples = n_frames * n_channels
        seg_len = max(1, total_samples // bars)
        values = []
        for b in range(bars):
            start = b * seg_len * 2
            end = min(start + seg_len * 2, len(raw))
            if start >= end:
                values.append(0.0)
                continue
            # Pico do segmento (nao media) — mais fiel a altura real do som,
            # mesma logica da onda ao vivo (AudioRecorder._callback)
            seg_peak = 0
            for i in range(start, end - 1, 2):
                v = struct.unpack_from('<h', raw, i)[0]
                if v < 0:
                    v = -v
                if v > seg_peak:
                    seg_peak = v
            values.append(seg_peak / 32768.0)
        peak = max(values) if values else 0.0
        if peak <= 0:
            return [0.15] * bars
        return [min(1.0, max(0.08, v / peak)) for v in values]
    except Exception:
        return [0.3] * bars

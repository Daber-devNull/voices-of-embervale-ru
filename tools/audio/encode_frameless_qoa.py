"""Экспериментальный моно QOA encoder; сохраняет игровой формат и длительность."""
import argparse
import hashlib
import json
import math
import struct
import sys
import wave
from array import array
from pathlib import Path
from decode_frameless_qoa import DEQUANT, decode, statistics, PROJECT


def encode(samples):
    history, weights = [0]*4, [0, 0, -8192, 16384]
    result = bytearray()
    for start in range(0, len(samples), 20):
        source = samples[start:start+20]
        best = None
        for scale, row in enumerate(DEQUANT):
            h0,h1,h2,h3 = history
            w0,w1,w2,w3 = weights
            error, packed = 0, scale << 60
            for j, value in enumerate(source):
                prediction = (h0*w0+h1*w1+h2*w2+h3*w3) >> 13
                difference = value-prediction
                magnitude = abs(difference)*2
                level = 0 if magnitude <= row[0]+row[2] else 1 if magnitude <= row[2]+row[4] else 2 if magnitude <= row[4]+row[6] else 3
                code = level*2 + (difference < 0)
                residual = row[code]
                reconstructed = max(-32768, min(32767, prediction+residual))
                error += (value-reconstructed)**2
                packed |= code << (57-3*j)
                adjustment = residual >> 4
                w0 += -adjustment if h0<0 else adjustment
                w1 += -adjustment if h1<0 else adjustment
                w2 += -adjustment if h2<0 else adjustment
                w3 += -adjustment if h3<0 else adjustment
                h0,h1,h2,h3 = h1,h2,h3,reconstructed
            if best is None or error < best[0]:
                best = error, packed, [h0,h1,h2,h3], [w0,w1,w2,w3]
        _, packed, history, weights = best
        result.extend(struct.pack('<Q', packed))
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_wave', type=Path)
    parser.add_argument('--voice', default='не указан')
    parser.add_argument('--original-directory', type=Path,
                        default=PROJECT/'local/farmer-letter-001')
    args = parser.parse_args()
    source = args.input_wave.resolve()
    if not source.is_relative_to(PROJECT/'local'):
        raise ValueError('Вход должен находиться в local')
    original_dir = args.original_directory.resolve()
    if not original_dir.is_relative_to(PROJECT/'local'):
        raise ValueError('Оригинал должен находиться в local')
    original = json.loads((original_dir/'metadata.json').read_text(encoding='utf-8'))
    with wave.open(str(source), 'rb') as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1,2,48000):
            raise ValueError('Нужен PCM16 mono 48 kHz')
        pcm = w.readframes(w.getnframes())
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    source_frames = len(samples)
    frames = original['frame_count']
    if not 0 < source_frames <= frames:
        raise ValueError('Русская речь должна помещаться в исходную длительность')
    # Подгоняем средний уровень с учётом будущей тишины, без ограничения пиков.
    validation_files = list(original_dir.glob('*.validation.json'))
    if len(validation_files) != 1:
        raise ValueError('Ожидается один отчет проверки оригинала')
    original_stats = json.loads(validation_files[0].read_text(encoding='utf-8'))['metrics']
    energy = sum(s*s for s in samples)
    if energy == 0:
        raise ValueError('Исходная запись пуста')
    gain = min(original_stats['rms']/math.sqrt(energy/frames), 30000/max(abs(s) for s in samples))
    samples = array('h', (round(s*gain) for s in samples))
    samples.extend([0]*(frames-source_frames))
    output = source.parent/'russian.frameless-qoa.bin'
    preview = source.parent/'russian-roundtrip.wav'
    report = source.parent/'encoding.json'
    if any(p.exists() for p in [output,preview,report]):
        raise ValueError('Перезапись запрещена')
    encoded = encode(samples)
    reconstructed = decode(encoded, frames)
    error = math.sqrt(sum((a-b)**2 for a,b in zip(samples,reconstructed))/frames)
    snr = 20*math.log10(math.sqrt(sum(s*s for s in samples)/frames)/error) if error else None
    if len(encoded) != original['size']:
        raise ValueError('Размер не совпал с оригиналом')
    output.write_bytes(encoded)
    result = dict(source_frames=source_frames, target_frames=frames, sample_rate=48000,
                  voice=args.voice, gain=gain,
                  padding_seconds=(frames-source_frames)/48000,
                  encoded_size=len(encoded), encoded_sha256=hashlib.sha256(encoded).hexdigest(),
                  roundtrip_error_rms=error, snr_db=snr, metrics=statistics(reconstructed,48000),
                  listening_verified=False, game_playback_verified=False)
    if sys.byteorder != 'little':
        reconstructed.byteswap()
    with wave.open(str(preview),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(reconstructed.tobytes())
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

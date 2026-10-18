"""Экспериментальный декодер моно FramelessQOA данной сборки в PCM16 WAV.

QOA specification: https://github.com/phoboslab/qoa (Dominic Szablewski, MIT).
Независимая реализация на Python. Игровые slices имеют little-endian порядок;
остатки читаются от старших битов. Состояние LMS непрерывно на всю запись.
"""
import argparse
import hashlib
import json
import math
import struct
import sys
import wave
from array import array
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SCALES = [round((i + 1) ** 2.75) for i in range(16)]
MAGNITUDES = [.75, .75, 2.5, 2.5, 4.5, 4.5, 7, 7]
DEQUANT = [[int(scale * value + .5) * (1 if i % 2 == 0 else -1)
            for i, value in enumerate(MAGNITUDES)] for scale in SCALES]


def decode(data, frames):
    if frames <= 0 or len(data) != ((frames + 19) // 20) * 8:
        raise ValueError('Размер slices не соответствует числу кадров')
    history = [0, 0, 0, 0]
    weights = [0, 0, -8192, 16384]
    samples = array('h')
    for (packed,) in struct.iter_unpack('<Q', data):
        residuals = DEQUANT[packed >> 60]
        for j in range(min(20, frames - len(samples))):
            residual = residuals[(packed >> (57 - 3 * j)) & 7]
            prediction = sum(h * w for h, w in zip(history, weights)) >> 13
            sample = max(-32768, min(32767, prediction + residual))
            samples.append(sample)
            adjustment = residual >> 4
            weights = [w + (-adjustment if h < 0 else adjustment)
                       for h, w in zip(history, weights)]
            history = history[1:] + [sample]
    return samples


def statistics(samples, rate):
    n = len(samples)
    rms = math.sqrt(sum(s * s for s in samples) / n)
    dc = sum(samples) / n
    difference = math.sqrt(sum((samples[i] - samples[i-1]) ** 2 for i in range(1, n)) / max(1, n-1))
    return dict(frames=n, sample_rate=rate, duration_seconds=n/rate,
                minimum=min(samples), maximum=max(samples), rms=rms,
                rms_dbfs=20 * math.log10(rms / 32768) if rms else None,
                dc_offset=dc, adjacent_difference_rms=difference,
                full_scale_samples=sum(s in (-32768, 32767) for s in samples))


def convert(directory, output):
    directory, output = directory.resolve(), output.resolve()
    local = PROJECT / 'local'
    if not directory.is_relative_to(local) or not output.is_relative_to(local) or output.suffix.lower() != '.wav':
        raise ValueError('Вход и WAV должны находиться в local проекта')
    report = output.with_suffix('.validation.json')
    if output.exists() or report.exists():
        raise ValueError('Перезапись результата запрещена')
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    if metadata['codec'] != 'FramelessQOA' or metadata['channel_configuration'] != 'Mono':
        raise ValueError('Пока поддерживается только моно FramelessQOA')
    rate, frames = metadata['sample_rate'], metadata['frame_count']
    if not 8000 <= rate <= 192000 or not 0 < frames <= rate * 600:
        raise ValueError('Недопустимые параметры или длительность больше 10 минут')
    encoded = (directory / 'audio.frameless-qoa.bin').read_bytes()
    if hashlib.sha256(encoded).hexdigest() != metadata['audio_sha256']:
        raise ValueError('SHA256 входного аудиоблока не совпадает')
    samples = decode(encoded, frames)
    metrics = statistics(samples, rate)
    if sys.byteorder != 'little':
        samples.byteswap()
    pcm = samples.tobytes()
    with output.open('xb') as f:
        with wave.open(f, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
    with wave.open(str(output), 'rb') as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) != (1, 2, rate, frames):
            raise ValueError('Параметры WAV не совпали')
        if w.readframes(frames + 1) != pcm:
            raise ValueError('PCM после чтения WAV не совпал')
    result = dict(source_name=metadata['name'], source_sha256=metadata['audio_sha256'],
                  wav_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  pcm_sha256=hashlib.sha256(pcm).hexdigest(), metrics=metrics,
                  assumptions=dict(slice_byte_order='little', residual_order='MSB first',
                                   initial_history=[0, 0, 0, 0], initial_weights=[0, 0, -8192, 16384],
                                   state_reset='Только в начале записи'),
                  validation='Размер, SHA256 источника, число кадров и повторное чтение PCM проверены',
                  listening_verified=False, game_decoder_equivalence_verified=False)
    with report.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample_directory', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = convert(args.sample_directory, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Token and value normalizer.

Canonicalizes resolution, source, codec, audio codec tokens
without losing original value.
"""

from __future__ import annotations

import re


# Resolution normalization
RESOLUTION_MAP: dict[str, str] = {
    "360p": "360p", "480p": "480p", "576p": "576p",
    "720p": "720p", "hd": "720p",
    "1080p": "1080p", "fhd": "1080p",
    "1440p": "1440p", "2k": "1440p",
    "2160p": "2160p", "4k": "2160p", "uhd": "2160p",
    "4320p": "4320p", "8k": "4320p",
}

# Source normalization
SOURCE_MAP: dict[str, str] = {
    "web-dl": "WEB-DL", "webdl": "WEB-DL",
    "webrip": "WEBRip", "web-rip": "WEBRip",
    "bluray": "BluRay", "blu-ray": "BluRay", "bdrip": "BDRip",
    "brrip": "BRRip", "hdrip": "HDRip",
    "dvdrip": "DVDRip", "dvd-rip": "DVDRip",
    "hdtv": "HDTV",
    "cam": "CAM", "ts": "TS", "telesync": "TS",
    "remux": "REMUX",
}

# Codec normalization
CODEC_MAP: dict[str, str] = {
    "x264": "x264", "h264": "H.264", "h.264": "H.264", "avc": "H.264",
    "x265": "x265", "h265": "H.265", "h.265": "H.265", "hevc": "HEVC",
    "av1": "AV1",
    "vp9": "VP9", "vp8": "VP8",
    "divx": "DivX", "xvid": "XviD",
    "mpeg2": "MPEG2", "mpeg4": "MPEG4",
}

# Audio codec normalization
AUDIO_CODEC_MAP: dict[str, str] = {
    "aac": "AAC", "ac3": "AC3", "eac3": "EAC3", "e-ac3": "EAC3",
    "dts": "DTS", "truehd": "TrueHD", "atmos": "Atmos",
    "flac": "FLAC", "opus": "Opus", "vorbis": "Vorbis",
    "mp3": "MP3", "pcm": "PCM", "dolbydigital": "DolbyDigital",
    "dolbyatmos": "DolbyAtmos", "dts-hd": "DTS-HD",
}

# Combined lookup for "is this token a known technical marker?"
ALL_TECHNICAL: dict[str, str] = {}
ALL_TECHNICAL.update({k.lower(): v for k, v in RESOLUTION_MAP.items()})
ALL_TECHNICAL.update({k.lower(): v for k, v in SOURCE_MAP.items()})
ALL_TECHNICAL.update({k.lower(): v for k, v in CODEC_MAP.items()})
ALL_TECHNICAL.update({k.lower(): v for k, v in AUDIO_CODEC_MAP.items()})
ALL_TECHNICAL["hdr"] = "HDR"
ALL_TECHNICAL["hdr10"] = "HDR10"
ALL_TECHNICAL["hdr10+"] = "HDR10+"
ALL_TECHNICAL["dolby"] = "Dolby"
ALL_TECHNICAL["imax"] = "IMAX"
ALL_TECHNICAL["proper"] = "PROPER"
ALL_TECHNICAL["repack"] = "REPACK"
ALL_TECHNICAL["internal"] = "INTERNAL"
ALL_TECHNICAL["extended"] = "EXTENDED"
ALL_TECHNICAL["unrated"] = "UNRATED"
ALL_TECHNICAL["directors"] = "DIRECTORS"
ALL_TECHNICAL["dual"] = "DUAL"
ALL_TECHNICAL["multi"] = "MULTI"


def normalize_token(token: str) -> str | None:
    """Return canonical form if token is a known technical marker, else None."""
    return ALL_TECHNICAL.get(token.lower())


def normalize_resolution(token: str) -> str | None:
    return RESOLUTION_MAP.get(token.lower())


def normalize_source(token: str) -> str | None:
    return SOURCE_MAP.get(token.lower())


def normalize_codec(token: str) -> str | None:
    return CODEC_MAP.get(token.lower())


def normalize_audio_codec(token: str) -> str | None:
    return AUDIO_CODEC_MAP.get(token.lower())


def is_technical_marker(token: str) -> bool:
    """Check if a token is a known technical marker (resolution, source, codec, etc.)."""
    return token.lower() in ALL_TECHNICAL


def is_year(token: str) -> bool:
    """Check if token looks like a year (1900-2099)."""
    return bool(re.match(r'^(19\d\d|20\d\d)$', token))

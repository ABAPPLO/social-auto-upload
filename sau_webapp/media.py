# -*- coding: utf-8 -*-
"""素材媒体处理：视频封面帧提取与时长探测（opencv），结果缓存到 uploadFile/.thumbs/。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2

POSTER_WIDTH = 480


def _thumbs_dir(material_dir: Path) -> Path:
    thumbs = material_dir / ".thumbs"
    thumbs.mkdir(exist_ok=True)
    return thumbs


def poster_file(material_dir: Path, name: str) -> Path:
    return _thumbs_dir(material_dir) / f"{name}.jpg"


def meta_file(material_dir: Path, name: str) -> Path:
    return _thumbs_dir(material_dir) / f"{name}.json"


def ensure_video_meta(material: Path, material_dir: Path) -> dict[str, Any]:
    """提取视频封面帧 + 时长/分辨率，按素材 mtime 缓存；损坏文件返回零值元信息。"""
    mtime = material.stat().st_mtime
    poster_path = poster_file(material_dir, material.name)
    meta_path = meta_file(material_dir, material.name)
    if poster_path.exists() and meta_path.exists():
        try:
            cached = json.loads(meta_path.read_text(encoding="utf-8"))
            if cached.get("mtime") == mtime:
                return cached
        except (ValueError, OSError):
            pass

    meta: dict[str, Any] = {"duration": 0, "width": 0, "height": 0, "mtime": mtime}
    cap = cv2.VideoCapture(str(material))
    try:
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            if fps > 0 and frames > 0:
                meta["duration"] = round(frames / fps, 1)
            meta["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            meta["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

            # 封面取 ~1s 处的帧；短视频回退到 10% 位置
            target = int(fps * 1) if fps else 0
            if frames and target >= frames:
                target = int(frames * 0.1)
            if target:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, frame = cap.read()
            if ok and frame is not None:
                height, width = frame.shape[:2]
                if width > POSTER_WIDTH:
                    frame = cv2.resize(frame, (POSTER_WIDTH, max(1, int(height * POSTER_WIDTH / width))))
                cv2.imwrite(str(poster_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    finally:
        cap.release()

    try:
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    except OSError:
        pass
    return meta

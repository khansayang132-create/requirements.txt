"""Timeline assembly with ffmpeg: scene clips, narration, music bed, ducking, loudness, subtitles."""
from __future__ import annotations

from pathlib import Path

from .media import probe_duration, run_ffmpeg
from .models import Storyboard

TARGET_LUFS = -14.0
FONT = "DejaVu Sans"


def encode_scene_clip(frames_dir: Path, out: Path, fps: int, fade_in: bool, fade_out: bool, duration: float) -> Path:
    vf = []
    if fade_in:
        vf.append("fade=t=in:st=0:d=0.4")
    if fade_out:
        vf.append(f"fade=t=out:st={max(0.0, duration - 0.5):.3f}:d=0.5")
    vf.append("format=yuv420p")
    run_ffmpeg(["-framerate", str(fps), "-i", str(frames_dir / "frame_%04d.png"), "-vf", ",".join(vf),
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(fps), str(out)])
    return out


def concat_clips(clips: list[Path], out: Path) -> Path:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    return out


def narration_track(board: Storyboard, wavs: list[Path], out: Path) -> Path:
    """Place each scene's narration at its scene start; pad to the full timeline length."""
    args, labels = [], []
    for i, (scene, wav) in enumerate(zip(board.scenes, wavs)):
        args += ["-i", str(wav)]
        ms = int(round(scene.start_time * 1000))
        labels.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,adelay={ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(wavs)))
    total = board.total_seconds
    graph = ";".join(labels) + f";{mix}amix=inputs={len(wavs)}:normalize=0,apad,atrim=0:{total:.3f}[out]"
    run_ffmpeg([*args, "-filter_complex", graph, "-map", "[out]", "-ar", "44100", "-ac", "1", str(out)])
    return out


def music_bed(seconds: float, out: Path) -> Path:
    """An original, procedurally generated ambient pad (A minor), so no license is involved."""
    src = (f"sine=f=110:d={seconds:.3f},volume=0.5[a];sine=f=220:d={seconds:.3f},volume=0.35[b];"
           f"sine=f=261.63:d={seconds:.3f},volume=0.25[c];sine=f=329.63:d={seconds:.3f},volume=0.2[d];"
           f"[a][b][c][d]amix=inputs=4:normalize=0,tremolo=f=0.25:d=0.35,lowpass=f=900,"
           f"afade=t=in:d=1.5,afade=t=out:st={max(0.0, seconds - 2):.3f}:d=2,volume=0.35[m]")
    run_ffmpeg(["-filter_complex", src, "-map", "[m]", "-t", f"{seconds:.3f}", "-ar", "44100", "-ac", "1", str(out)])
    return out


def mix_audio(narration: Path, music: Path, out: Path) -> Path:
    """Duck the music under the voice, mix, and normalize to the platform loudness target."""
    graph = ("[1:a]asplit=2[sc][voice];"
             "[0:a][sc]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[ducked];"
             "[ducked][voice]amix=inputs=2:normalize=0:weights='0.6 1',"
             f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11,aresample=44100[out]")
    run_ffmpeg(["-i", str(music), "-i", str(narration), "-filter_complex", graph, "-map", "[out]",
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


# libass lays out SRT subtitles on a virtual 288-line canvas, so sizes and margins are in those units.
ASS_PLAY_RES_Y = 288


def _srt_filter(path: Path, style: str) -> str:
    arg = str(path).replace("\\", "/").replace(":", r"\:")
    return f"subtitles='{arg}':force_style='{style}'"


def burn_and_mux(video: Path, audio: Path, srt: Path, out: Path, width: int, height: int,
                 titles: Path | None = None) -> Path:
    u = ASS_PLAY_RES_Y
    # Captions sit above the platform UI (bottom ~25% of a 9:16 frame); headlines below the top tabs.
    # force_style on SRT uses legacy SSA alignment numbers: 2 = bottom centre, 6 = top centre.
    caption = (f"FontName={FONT},FontSize={round(u * 0.042)},Bold=1,PrimaryColour=&H00FFFFFF,"
               f"OutlineColour=&H00000000,BorderStyle=1,Outline=1.2,Shadow=0,Alignment=2,"
               f"MarginV={round(u * 0.27)},MarginL=16,MarginR=16")
    headline = (f"FontName={FONT},FontSize={round(u * 0.062)},Bold=1,PrimaryColour=&H0000D7FF,"
                f"OutlineColour=&H00000000,BorderStyle=1,Outline=1.6,Shadow=0,Alignment=6,"
                f"MarginV={round(u * 0.13)},MarginL=14,MarginR=14")
    filters = ([_srt_filter(titles, headline)] if titles else []) + [_srt_filter(srt, caption)]
    run_ffmpeg(["-i", str(video), "-i", str(audio),
                "-vf", ",".join(filters),
                "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out)])
    return out


def assemble(board: Storyboard, frame_dirs: list[Path], wavs: list[Path], srt: Path, work: Path, out: Path,
             titles: Path | None = None) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, (scene, fdir) in enumerate(zip(board.scenes, frame_dirs)):
        clips.append(encode_scene_clip(fdir, work / f"{scene.scene_id}.mp4", board.fps,
                                       scene.transition_in == "fade", scene.transition_out == "fade", scene.duration))
    video = concat_clips(clips, work / "video.mp4")
    narr = narration_track(board, wavs, work / "narration.wav")
    music = music_bed(board.total_seconds, work / "music.wav")
    audio = mix_audio(narr, music, work / "audio.m4a")
    burn_and_mux(video, audio, srt, out, board.width, board.height, titles)
    return {"clips": [str(c) for c in clips], "video_only": str(video), "narration": str(narr),
            "music": str(music), "music_source": "procedurally generated sine pad (original, no license required)",
            "audio": str(audio), "final": str(out), "final_seconds": probe_duration(out)}

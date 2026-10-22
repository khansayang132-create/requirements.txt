"""Turn a locked script plus measured narration lengths into a validated storyboard."""
from __future__ import annotations

from .models import SceneSpec, Script, Storyboard
from .timing import allocate

RESOLUTIONS = {"9:16": (432, 768), "1:1": (720, 720), "16:9": (768, 432)}


def build_storyboard(script: Script, narration_seconds: list[float], aspect_ratio: str, fps: int) -> Storyboard:
    if len(narration_seconds) != len(script.scenes):
        raise ValueError("need one narration length per scene")
    width, height = RESOLUTIONS[aspect_ratio]
    scenes = []
    for i, (sc, (start, end, dur)) in enumerate(zip(script.scenes, allocate(narration_seconds, fps))):
        scenes.append(SceneSpec(
            scene_id=sc.scene_id,
            scene_order=i,
            start_time=start,
            end_time=end,
            duration=dur,
            narrative_purpose=sc.purpose,
            narration_text=sc.narration,
            subtitle_text=sc.narration,
            on_screen_text=sc.on_screen_text,
            template=sc.template,
            camera_move=sc.camera_move,
            params=sc.params,
            transition_in="fade" if i == 0 else "cut",
            transition_out="fade" if i == len(script.scenes) - 1 else "cut",
            music_cue=sc.music_cue,
        ))
    return Storyboard(script_version=script.version_hash, fps=fps, width=width, height=height, scenes=scenes)

"""Small-scale smoke test for each YouTube pipeline component.

Tests each service individually with minimal data to verify API keys
and integrations work before running the full pipeline.

Usage:
    PYTHONPATH=. .venv/bin/python -m prolific.youtube.smoke_test
"""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("smoke_test")


async def test_topic_selection():
    logger.info("--- TEST 1: Topic Selection (LLM) ---")
    from prolific.youtube.state import create_initial_youtube_state
    from prolific.youtube.nodes.topic_selection import topic_selection_node

    state = create_initial_youtube_state()
    result = await topic_selection_node(state)
    topic = result.get("topic", "")
    assert topic, "No topic selected"
    logger.info(f"PASS: Selected topic: {topic}")
    return topic


async def test_script_writing(topic: str):
    logger.info("--- TEST 2: Script Writing (LLM, ~200 words) ---")
    from langchain_core.messages import HumanMessage, SystemMessage
    from prolific.services.llm import get_llm_service

    llm = get_llm_service()
    response = await llm.invoke(
        messages=[
            SystemMessage(content="Write a calm, sleep-friendly narration about a historical topic. "
                          "About 200 words. Flowing prose, no headers."),
            HumanMessage(content=f"Topic: {topic}"),
        ],
        tier="research",
        temperature=0.7,
        max_tokens=1024,
    )
    word_count = len(response.content.split())
    assert word_count > 50, f"Script too short: {word_count} words"
    logger.info(f"PASS: Generated {word_count} words of narration")
    logger.info(f"  Preview: {response.content[:150]}...")
    return response.content


async def test_image_generation(topic: str):
    logger.info("--- TEST 3: Image Generation (Nano Banana 2) ---")
    from prolific.youtube.services.image_gen import get_image_gen_service
    from prolific.core.config import settings

    output_dir = Path(settings.youtube_output_dir) / "smoke_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "test_image.png")

    service = get_image_gen_service()
    await service.generate_image(
        prompt=f"A cinematic historical scene related to {topic}. Wide landscape, warm lighting.",
        output_path=output_path,
    )

    file_size = Path(output_path).stat().st_size
    assert file_size > 1000, f"Image too small: {file_size} bytes"
    logger.info(f"PASS: Image generated: {output_path} ({file_size / 1024:.0f} KB)")
    return output_path


async def test_tts(script_text: str):
    logger.info("--- TEST 4: 11Labs TTS ---")
    from prolific.youtube.services.tts import get_tts_service
    from prolific.core.config import settings

    output_dir = Path(settings.youtube_output_dir) / "smoke_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "test_audio.mp3")

    short_text = script_text[:500]

    service = get_tts_service()
    duration = await service.synthesize_text(short_text, output_path)

    file_size = Path(output_path).stat().st_size
    assert file_size > 1000, f"Audio too small: {file_size} bytes"
    logger.info(f"PASS: Audio generated: {output_path} ({file_size / 1024:.0f} KB, ~{duration:.0f}s)")
    return output_path, duration


async def test_video_assembly(image_path: str, audio_path: str):
    logger.info("--- TEST 5: Video Assembly (ffmpeg) ---")
    from prolific.youtube.services.video import get_video_assembly_service
    from prolific.core.config import settings

    output_dir = Path(settings.youtube_output_dir) / "smoke_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    clip_path = str(output_dir / "test_clip.mp4")
    video_service = get_video_assembly_service()

    await video_service.create_ken_burns_clip(
        image_path=image_path,
        duration=10.0,
        output_path=clip_path,
        direction="zoom_in",
    )
    assert Path(clip_path).stat().st_size > 1000, "Ken Burns clip too small"
    logger.info(f"PASS: Ken Burns clip: {clip_path}")

    final_path = str(output_dir / "test_final.mp4")
    await video_service.assemble_video(
        clip_paths=[clip_path],
        audio_path=audio_path,
        output_path=final_path,
    )
    file_size = Path(final_path).stat().st_size
    assert file_size > 1000, "Final video too small"
    logger.info(f"PASS: Final video: {final_path} ({file_size / 1024:.0f} KB)")
    return final_path


async def test_channel_history():
    logger.info("--- TEST 6: Channel History DB ---")
    from prolific.youtube.services.channel_history import get_channel_history_service
    from prolific.youtube.schemas import VideoRecord

    service = get_channel_history_service()
    await service.initialize()

    record = VideoRecord(
        topic="Smoke Test Topic",
        title="Test Video",
        status="test",
    )
    await service.record_video(record)

    topics = await service.get_past_topics(limit=10)
    assert "Smoke Test Topic" in topics, "Topic not found in history"
    logger.info(f"PASS: Channel history working ({len(topics)} topics stored)")


async def main():
    logger.info("=" * 60)
    logger.info("YOUTUBE PIPELINE SMOKE TEST")
    logger.info("=" * 60)

    results = {}

    try:
        topic = await test_topic_selection()
        results["topic_selection"] = "PASS"
    except Exception as e:
        logger.error(f"FAIL: Topic selection: {e}")
        results["topic_selection"] = f"FAIL: {e}"
        topic = "The Roman Empire"

    try:
        script = await test_script_writing(topic)
        results["script_writing"] = "PASS"
    except Exception as e:
        logger.error(f"FAIL: Script writing: {e}")
        results["script_writing"] = f"FAIL: {e}"
        script = "The ancient world was a place of wonder and mystery."

    try:
        image_path = await test_image_generation(topic)
        results["image_generation"] = "PASS"
    except Exception as e:
        logger.error(f"FAIL: Image generation: {e}")
        results["image_generation"] = f"FAIL: {e}"
        image_path = None

    try:
        audio_path, duration = await test_tts(script)
        results["tts"] = "PASS"
    except Exception as e:
        logger.error(f"FAIL: TTS: {e}")
        results["tts"] = f"FAIL: {e}"
        audio_path = None

    if image_path and audio_path:
        try:
            video_path = await test_video_assembly(image_path, audio_path)
            results["video_assembly"] = "PASS"
        except Exception as e:
            logger.error(f"FAIL: Video assembly: {e}")
            results["video_assembly"] = f"FAIL: {e}"
    else:
        results["video_assembly"] = "SKIP (missing image or audio)"

    try:
        await test_channel_history()
        results["channel_history"] = "PASS"
    except Exception as e:
        logger.error(f"FAIL: Channel history: {e}")
        results["channel_history"] = f"FAIL: {e}"

    logger.info("")
    logger.info("=" * 60)
    logger.info("RESULTS SUMMARY")
    logger.info("=" * 60)
    all_pass = True
    for test_name, result in results.items():
        status = "PASS" if result == "PASS" else "FAIL"
        if status == "FAIL":
            all_pass = False
        logger.info(f"  {test_name}: {result}")

    logger.info("=" * 60)
    if all_pass:
        logger.info("ALL TESTS PASSED")
    else:
        logger.info("SOME TESTS FAILED")
    logger.info("=" * 60)
    logger.info("(YouTube upload skipped - create channel first, then run auth.py)")

    return 0 if all_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

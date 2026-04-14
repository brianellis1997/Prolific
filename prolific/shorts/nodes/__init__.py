"""Short-form pipeline node implementations."""

from prolific.shorts.nodes.clip_analysis import clip_analysis_node
from prolific.shorts.nodes.clip_director import clip_director_node
from prolific.shorts.nodes.clip_sourcing import clip_sourcing_node
from prolific.shorts.nodes.compilation_research import compilation_research_node
from prolific.shorts.nodes.image_generation import image_generation_node
from prolific.shorts.nodes.metadata_generation import metadata_generation_node
from prolific.shorts.nodes.script_writing import script_writing_node
from prolific.shorts.nodes.stock_clip_sourcing import stock_clip_sourcing_node
from prolific.shorts.nodes.story_direction import story_direction_node
from prolific.shorts.nodes.story_review import story_review_node
from prolific.shorts.nodes.topic_selection import topic_selection_node
from prolific.shorts.nodes.tts_generation import tts_generation_node
from prolific.shorts.nodes.streaming_discovery import streaming_discovery_node
from prolific.shorts.nodes.twitch_discovery import twitch_discovery_node
from prolific.shorts.nodes.video_assembly import video_assembly_node
from prolific.shorts.nodes.visual_planning import visual_planning_node
from prolific.shorts.nodes.youtube_upload import youtube_upload_node

__all__ = [
    "clip_director_node",
    "topic_selection_node",
    "streaming_discovery_node",
    "twitch_discovery_node",
    "clip_analysis_node",
    "story_direction_node",
    "story_review_node",
    "script_writing_node",
    "visual_planning_node",
    "stock_clip_sourcing_node",
    "image_generation_node",
    "clip_sourcing_node",
    "compilation_research_node",
    "tts_generation_node",
    "video_assembly_node",
    "metadata_generation_node",
    "youtube_upload_node",
]

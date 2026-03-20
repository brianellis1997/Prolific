"""Short-form pipeline node implementations."""

from prolific.shorts.nodes.clip_analysis import clip_analysis_node
from prolific.shorts.nodes.clip_sourcing import clip_sourcing_node
from prolific.shorts.nodes.compilation_research import compilation_research_node
from prolific.shorts.nodes.image_generation import image_generation_node
from prolific.shorts.nodes.metadata_generation import metadata_generation_node
from prolific.shorts.nodes.script_writing import script_writing_node
from prolific.shorts.nodes.stock_clip_sourcing import stock_clip_sourcing_node
from prolific.shorts.nodes.topic_selection import topic_selection_node
from prolific.shorts.nodes.tts_generation import tts_generation_node
from prolific.shorts.nodes.video_assembly import video_assembly_node
from prolific.shorts.nodes.visual_planning import visual_planning_node
from prolific.shorts.nodes.youtube_upload import youtube_upload_node

__all__ = [
    "topic_selection_node",
    "clip_analysis_node",
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

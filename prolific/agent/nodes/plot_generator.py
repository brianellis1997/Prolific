"""Plot Generator node for creating data visualizations.

The Plot Generator Agent creates matplotlib/seaborn charts and graphs
based on VisualIntent specifications.
"""

import base64
import io
import logging
import tempfile
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import (
    FigureSpec,
    VisualAsset,
    VisualIntent,
    VisualType,
)
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class PlotCode(BaseModel):
    """Generated Python code for creating a plot."""

    code: str
    chart_type: str
    title: str
    caption: str
    alt_text: str


PLOT_GENERATOR_PROMPT = """You are an expert data visualization developer. Generate Python code using matplotlib and/or seaborn to create a chart.

Visual Intent:
- Description: {description}
- Chart Type Hint: {chart_type}
- Purpose: {purpose}

Available Data:
{data_info}

Requirements:
1. Use matplotlib.pyplot as plt and optionally seaborn as sns
2. Create a clear, professional visualization
3. Include title, axis labels, and legend if applicable
4. Use a clean, readable style
5. Save the figure to the path: {output_path}
6. Set figure size to (10, 6) for good resolution
7. Use tight_layout() before saving
8. Do NOT call plt.show()

Generate:
1. code: Complete, runnable Python code
2. chart_type: The actual chart type used
3. title: A descriptive title for the chart
4. caption: A 1-2 sentence caption explaining what the chart shows
5. alt_text: Accessible description for screen readers
"""


def execute_plot_code(code: str, output_path: str) -> bool:
    """Execute plot generation code in a safe manner.

    Args:
        code: Python code to execute
        output_path: Path where the plot should be saved

    Returns:
        True if execution succeeded, False otherwise
    """
    try:
        exec_globals = {
            "__builtins__": __builtins__,
        }

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
            import pandas as pd

            exec_globals.update({
                "plt": plt,
                "sns": sns,
                "np": np,
                "pd": pd,
                "matplotlib": matplotlib,
            })
        except ImportError as e:
            logger.warning(f"Missing plotting library: {e}")
            return False

        exec(code, exec_globals)
        return Path(output_path).exists()

    except Exception as e:
        logger.error(f"Plot execution failed: {e}")
        return False


async def plot_generator_node(state: ContentGenerationState) -> dict:
    """Generate data visualizations for plot-type visual intents.

    This node:
    1. Filters visual intents for plot types
    2. Generates Python code for each plot
    3. Executes code to create images
    4. Creates VisualAsset artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with visual_assets to merge into state
    """
    logger.info("=== PLOT GENERATION PHASE ===")

    visual_intents = state.get("visual_intents", [])
    claims = {str(c.id): c for c in state.get("claims", [])}

    plot_intents = [
        intent for intent in visual_intents
        if intent.visual_type == VisualType.PLOT
    ]

    if not plot_intents:
        logger.info("No plot intents to generate")
        return {
            "messages": [AIMessage(content="No plots to generate.")],
        }

    logger.info(f"Generating {len(plot_intents)} plots")

    llm_service = get_llm_service()
    visual_assets = []

    for intent in plot_intents:
        try:
            data_info = "No specific data provided. Use synthetic/example data that illustrates the concept."
            if intent.data_requirements:
                data_info = f"Data requirements: {intent.data_requirements}"

            if intent.related_claims:
                related_claim_texts = []
                for claim_id in intent.related_claims[:3]:
                    claim = claims.get(str(claim_id))
                    if claim:
                        related_claim_texts.append(claim.statement)
                if related_claim_texts:
                    data_info += f"\n\nRelated facts to illustrate:\n" + "\n".join(
                        f"- {t}" for t in related_claim_texts
                    )

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name

            system_message = SystemMessage(
                content=PLOT_GENERATOR_PROMPT.format(
                    description=intent.description,
                    chart_type=intent.purpose.value,
                    purpose=intent.purpose.value,
                    data_info=data_info,
                    output_path=output_path,
                )
            )

            user_message = HumanMessage(
                content="Generate the plot code now."
            )

            try:
                result = await llm_service.invoke_with_structured_output(
                    messages=[system_message, user_message],
                    output_schema=PlotCode,
                    tier="research",
                    temperature=0.3,
                )
            except Exception as e:
                logger.warning(f"Plot code generation failed for intent {intent.id}: {e}")
                continue

            success = execute_plot_code(result.code, output_path)

            if success and Path(output_path).exists():
                with open(output_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")

                asset = VisualAsset(
                    id=uuid4(),
                    intent_id=intent.id,
                    visual_type=VisualType.PLOT,
                    source="plot",
                    file_path=output_path,
                    base64_data=image_data,
                    caption=result.caption,
                    alt_text=result.alt_text,
                    format="png",
                    quality_score=0.8,
                    relevance_score=0.9,
                )
                visual_assets.append(asset)
                logger.info(f"Generated plot for intent {intent.id}")
            else:
                logger.warning(f"Plot execution failed for intent {intent.id}")

        except Exception as e:
            logger.error(f"Failed to generate plot for intent {intent.id}: {e}")

    logger.info(f"Plot generation complete: {len(visual_assets)} plots created")

    return {
        "visual_assets": visual_assets,
        "messages": [
            AIMessage(content=f"Generated {len(visual_assets)} data visualizations.")
        ],
    }

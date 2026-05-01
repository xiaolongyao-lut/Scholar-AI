# -*- coding: utf-8 -*-
"""layers package.

Keep this file lightweight to avoid importing optional dependencies (e.g. `python-docx`, `Pillow`)
when only a subset of layers is used.
"""

__all__ = [
    "e_layer_multimodal",
    "r_layer_hybrid_retriever",
    "a_layer_agent_coordinator",
    "k_layer_index_builder",
    "g_layer_academic_generator",
    "p_layer_presentation_word",
    "v_layer_volume_bundle",
    "contracts",
]

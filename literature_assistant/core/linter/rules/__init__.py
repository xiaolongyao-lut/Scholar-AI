# -*- coding: utf-8 -*-
"""Linter 规则包

所有规则文件放在这个目录下，会被自动导入注册。
"""

# 导入所有规则模块，触发 register_rule()
from . import correct_title_sentence_case
from . import correct_whitespace
from . import correct_doi
from . import correct_date
from . import correct_creators
from . import correct_chemical_formula
from . import correct_pages
from . import correct_language
from . import correct_journal
from . import correct_url
from . import correct_creators_advanced
from . import correct_title_advanced
from . import correct_date_advanced
from . import correct_fields
from . import detect_duplicates
from . import correct_tags_misc

__all__ = [
    "correct_title_sentence_case",
    "correct_whitespace",
    "correct_doi",
    "correct_date",
    "correct_creators",
    "correct_chemical_formula",
    "correct_pages",
    "correct_language",
    "correct_journal",
    "correct_url",
    "correct_creators_advanced",
    "correct_title_advanced",
    "correct_date_advanced",
    "correct_fields",
    "detect_duplicates",
    "correct_tags_misc",
]

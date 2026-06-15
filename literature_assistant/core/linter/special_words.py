# -*- coding: utf-8 -*-
"""特殊词汇表 - 用于 Sentence Case 转换

参考 Zotero Format Metadata 插件的特殊词汇保护：
https://github.com/northword/zotero-format-metadata/blob/main/src/modules/rules/correct-title-sentence-case.ts

这些词汇在转换为 Sentence Case 时应保持首字母大写。
"""

from typing import Final

# 化学元素周期表（118个元素）
CHEMICAL_ELEMENTS: Final[list[str]] = [
    # Period 1
    "H", "He",
    # Period 2
    "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    # Period 3
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    # Period 4
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    # Period 5
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
    # Period 6
    "Cs", "Ba", "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
    # Period 7
    "Fr", "Ra", "Ac", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
    # Lanthanides
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    # Actinides
    "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr",
]

# 排除 'Be'（因为它也是虚词 'be' 的大写形式）
CHEMICAL_ELEMENTS_FILTERED: Final[list[str]] = [e for e in CHEMICAL_ELEMENTS if e != "Be"]

# 地理词汇
GEOGRAPHY_WORDS: Final[list[str]] = [
    # 大洲
    "Asia", "Europe", "Africa", "North America", "South America",
    "Asian", "European", "African", "American",
    "Oceania", "Antarctica",
    # 大洋
    "Pacific Ocean", "Atlantic Ocean", "Indian Ocean", "Arctic Ocean",
    # 其他地理特征
    "Mediterranean", "Tibetan Plateau",
    "Yangtze River", "Yangtze", "Beijing–Tianjin–Hebei", "Yellow River", "Huang He",
]

# 日期词汇
DATE_WORDS: Final[list[str]] = [
    # 星期
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    # 月份
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# 行星
PLANET_WORDS: Final[list[str]] = [
    "Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
]

# 品牌名
BRANDS: Final[list[str]] = [
    "Apple", "Microsoft", "Google", "Amazon", "Alibaba", "Tencent",
    "Facebook", "Twitter", "Instagram",
    "YouTube", "Netflix", "Spotify", "Tidal",
    "Inc", "Ltd",
]

# 方位词（后面可以跟地名）
LOCALITY_WORDS: Final[list[str]] = [
    "north", "south", "east", "west",
    "northern", "southern", "eastern", "western",
    "southeast", "southwest", "northwest", "northeast",
    "southeastern", "southwestern", "northwestern", "northeastern",
    "over",  # 其他后可以跟地名的虚词
]

# 中国省会城市
CHINA_CAPITALS: Final[list[str]] = [
    "Beijing", "Tianjin", "Shijiazhuang", "Taiyuan", "Hohhot", "Shenyang",
    "Changchun", "Harbin", "Shanghai", "Nanjing", "Hangzhou", "Hefei",
    "Fuzhou", "Nanchang", "Jinan", "Zhengzhou", "Wuhan", "Changsha",
    "Guangzhou", "Nanning", "Haikou", "Chongqing", "Chengdu", "Guiyang",
    "Kunming", "Lhasa", "Xi'an", "Lanzhou", "Xining", "Yinchuan",
    "Urumqi", "Hong Kong", "Macao",
]

# 世界主要城市
WORLD_CITIES: Final[list[str]] = [
    # United States
    "New York", "Los Angeles", "San Francisco", "Chicago", "Miami",
    # United Kingdom
    "London",
    # France
    "Paris",
    # Germany
    "Berlin", "Munich",
    # Italy
    "Rome", "Milan",
    # Spain
    "Madrid", "Barcelona",
    # Netherlands
    "Amsterdam",
    # Belgium
    "Brussels",
    # Austria
    "Vienna",
    # Switzerland
    "Zurich",
    # Russia
    "Moscow", "Saint Petersburg",
    # Turkey
    "Istanbul",
    # UAE
    "Dubai", "Abu Dhabi",
    # Qatar
    "Doha",
    # Saudi Arabia
    "Riyadh",
    # Israel
    "Tel Aviv",
    # Singapore
    "Singapore",
    # Japan
    "Tokyo", "Osaka", "Kyoto",
    # South Korea
    "Seoul", "Busan",
    # Thailand
    "Bangkok",
    # Indonesia
    "Jakarta",
    # Malaysia
    "Kuala Lumpur",
    # Philippines
    "Manila",
    # Vietnam
    "Hanoi", "Ho Chi Minh City",
    # Australia
    "Sydney", "Melbourne",
    # New Zealand
    "Auckland",
    # Canada
    "Toronto", "Vancouver", "Montreal",
    # Mexico
    "Mexico City",
    # Brazil
    "São Paulo", "Rio de Janeiro",
    # Argentina
    "Buenos Aires",
    # Peru
    "Lima",
    # South Africa
    "Cape Town", "Johannesburg",
]

# 主要国家（从原插件的 country-by-capital-city.json 提取）
# 简化版，只包含常见国家
COUNTRIES: Final[list[str]] = [
    "Afghanistan", "Albania", "Algeria", "Argentina", "Australia", "Austria",
    "Bangladesh", "Belgium", "Brazil", "Bulgaria", "Canada", "Chile", "China",
    "Colombia", "Cuba", "Czech Republic", "Denmark", "Egypt", "Finland", "France",
    "Germany", "Greece", "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq",
    "Ireland", "Israel", "Italy", "Japan", "Jordan", "Kenya", "Kuwait", "Lebanon",
    "Malaysia", "Mexico", "Morocco", "Nepal", "Netherlands", "New Zealand", "Nigeria",
    "Norway", "Pakistan", "Peru", "Philippines", "Poland", "Portugal", "Romania",
    "Russia", "Saudi Arabia", "Singapore", "South Africa", "South Korea", "Spain",
    "Sweden", "Switzerland", "Syria", "Taiwan", "Thailand", "Turkey", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Venezuela", "Vietnam",
]

# Function words（虚词）- 在 Title Case 中应该小写
# 参考 Chicago Manual of Style 和 APA Style
FUNCTION_WORDS: Final[list[str]] = [
    # Articles
    "a", "an", "the",
    # Coordinating conjunctions
    "and", "but", "or", "nor", "for", "so", "yet",
    # Prepositions (short ones, typically < 5 letters)
    "at", "by", "in", "of", "on", "to", "up",
    "for", "from", "into", "like", "over", "with",
    "as", "per", "via",
]

# 所有特殊词汇的合集（需要保持首字母大写）
ALL_SPECIAL_WORDS: Final[list[str]] = [
    *BRANDS,
    *GEOGRAPHY_WORDS,
    *DATE_WORDS,
    *COUNTRIES,
    *CHINA_CAPITALS,
    *WORLD_CITIES,
    *PLANET_WORDS,
]

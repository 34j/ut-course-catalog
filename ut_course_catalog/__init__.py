"""Top-level package for ut-course-catalog."""

__author__ = """34j"""
__email__ = "34j@github.com"
__version__ = "0.1.0"
from .common import Semester, Weekday, BASE_URL
from .ja import UTCourseCatalog, SearchParams, Details, Faculty, Institution, ClassForm, Language, CommonCode

__all__ = [
    "Semester",
    "Weekday",
    "BASE_URL",
    "UTCourseCatalog",
    "SearchParams",
    "Details",
    "Faculty",
    "Institution",
    "ClassForm",
    "Language",
    "CommonCode",
]

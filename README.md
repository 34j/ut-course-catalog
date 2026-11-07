# UT Course Catalog

<p align="center">
  <a href="https://github.com/34j/ut-course-catalog/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/34j/ut-course-catalog/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://ut-course-catalog.readthedocs.io">
    <img src="https://img.shields.io/readthedocs/ut-course-catalog.svg?logo=read-the-docs&logoColor=fff&style=flat-square" alt="Documentation Status">
  </a>
</p>
<p align="center">
  <a href="https://codecov.io/gh/34j/ut-course-catalog">
    <img src="https://img.shields.io/codecov/c/github/34j/ut-course-catalog.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
  <a href="https://github.com/astral-sh/uv">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
  </a>
  <a href="https://github.com/j178/prek">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json" alt="prek">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/ut-course-catalog/">
    <img src="https://img.shields.io/pypi/v/ut-course-catalog.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/ut-course-catalog.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/ut-course-catalog.svg?style=flat-square" alt="License">
</p>

---

**Documentation**: <a href="https://ut-course-catalog.readthedocs.io" target="_blank">https://ut-course-catalog.readthedocs.io </a>

**Source Code**: <a href="https://github.com/34j/ut-course-catalog" target="_blank">https://github.com/34j/ut-course-catalog </a>

---

Python package for fetching UTokyo Online Course Catalogue

## Installation

Install this via pip (or your favourite package manager):

```shell
pip install ut-course-catalog
```

## Dataset

- 東京大学授業カタログはインターネット上で公開されており、誰でも無償で入手可能でした。
- robots.txtの内容は寛容的であり、ページはWayback Machineに登録されているため、情報収集は禁止されていないと考えられました。

したがって、著作権法第三十条の四に基づいて、[データセット](https://www.kaggle.com/datasets/mkrjas/utokyosyllabus)をKaggleに公開しています。適当に解析したノートブック[(GitHub)](https://github.com/34j/ut-course-catalog/blob/main/ut-course-catalog-tutorial.ipynb)もあります。

## Usage

1秒に1回のリクエストを送る場合、ダウンロードには4時間強かかります。負荷軽減のため、なるべく収集済みのデータセットを御利用ください。

```shell
ut-course-catalog download
ut-course-catalog convert all.pkl
```

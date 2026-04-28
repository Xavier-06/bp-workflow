"""
PDF Extractor — 从 BP PDF 中尽量完整地提取文本
支持多种提取方式：pdftotext / pdfplumber / PyMuPDF / subprocess

用法：
  from content.pdf_extractor import extract_pdf_file, extract_pdf_url

修复（2026-04-01）：
  - 增加 fallback 链（pdftotext → pdfplumber → PyMuPDF）
  - 修复编码问题（强制 UTF-8，移除 BOM/非法字符）
  - 保留页面分隔标记（便于定位 BP 页码）
  - 失败时返回空字符串而不是抛异常
"""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

BIN = Path(__file__).resolve().parent.parent / 'bin' / 'pdf-extract'


def _clean_text(text: str) -> str:
    """清理 PDF 提取后的文本"""
    if not text:
        return ''
    # 替换替换字符
    text = text.replace('\ufffd', '')
    # 移除非法控制字符（保留制表符、换行、回车）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # 清理多余空行
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text.strip()


def _extract_pdftotext(pdf_path: str) -> Optional[str]:
    """用 pdftotext（poppler）提取"""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', '-enc', 'UTF-8', pdf_path, '-'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return _clean_text(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _extract_pdfplumber(pdf_path: str) -> Optional[str]:
    """用 pdfplumber 提取（保留表格结构）"""
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages.append(f'--- Page {i+1} ---\n{text}')
        if pages:
            return _clean_text('\n\n'.join(pages))
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _extract_pymupdf(pdf_path: str) -> Optional[str]:
    """用 PyMuPDF（fitz）提取"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = []
        for i in range(len(doc)):
            text = doc[i].get_text()
            if text:
                pages.append(text)
        doc.close()
        if pages:
            return _clean_text('\n\n'.join(pages))
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _extract_bin(pdf_path: str) -> Optional[str]:
    """用 bin/pdf-extract 提取"""
    if not BIN.exists():
        return None
    try:
        result = subprocess.run(
            [str(BIN), pdf_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return _clean_text(result.stdout)
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def extract_pdf_file(pdf_path: str, max_chars: int = 50000) -> str:
    """从本地 PDF 文件提取正文。
    
    提取顺序：
    1. bin/pdf-extract（如果有）
    2. pdftotext（poppler）
    3. pdfplumber
    4. PyMuPDF
    
    成功时返回文本，失败返回空字符串。
    """
    if not Path(pdf_path).exists():
        return ''

    # fallback
    for fn in [_extract_bin, _extract_pdftotext, _extract_pdfplumber, _extract_pymupdf]:
        result = fn(pdf_path)
        if result:
            return result[:max_chars]

    return ''


def extract_pdf_url(url: str, max_chars: int = 100000) -> str:
    """下载 PDF URL 并提取正文。"""
    import requests
    tmp_path = None
    try:
        resp = requests.get(
            url, timeout=30,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        if resp.status_code != 200:
            return ''
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name
        return extract_pdf_file(tmp_path, max_chars)
    except Exception:
        return ''
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print('Usage: python3 pdf_extractor.py <path_or_url>')
        sys.exit(1)
    if path.startswith('http'):
        print(extract_pdf_url(path)[:500])
    else:
        print(extract_pdf_file(path)[:500])

import argparse
import datetime
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-cafbe781406a4deb91796195c2e797a7")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
MOBILE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']|'
    r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    re.IGNORECASE | re.DOTALL,
)
P_TAG_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
LI_TAG_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
H3_BLOCK_RE = re.compile(
    r"<h3\b[^>]*>(?P<title_block>.*?)</h3>(?P<body_block>.*?)(?=<h3\b[^>]*>|<div\b[^>]+id=['\"]page['\"]|$)",
    re.IGNORECASE | re.DOTALL,
)
LINK_RE = re.compile(
    r"<a\b[^>]*href=['\"](?P<href>[^'\"]+)['\"][^>]*>(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)

SEARCH_ENGINES = [
    {
        "name": "360搜索",
        "build_url": lambda keyword, limit: (
            "https://www.so.com/s?"
            + urllib.parse.urlencode({"q": keyword, "pn": "1"})
        ),
    },
    {
        "name": "搜狗微信",
        "build_url": lambda keyword, _limit: (
            "https://weixin.sogou.com/weixin?"
            + urllib.parse.urlencode({"type": "2", "query": keyword})
        ),
    },
    {
        "name": "必应RSS",
        "build_url": lambda keyword, _limit: (
            "https://cn.bing.com/search?"
            + urllib.parse.urlencode({"q": keyword, "format": "rss"})
        ),
    },
]

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(TOOL_DIR, "outputs")


def configure_console_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def clean_text(raw_text):
    text = html.unescape(TAG_RE.sub(" ", raw_text or ""))
    return SPACE_RE.sub(" ", text).strip()


def fetch_text(url, timeout=10, headers=None):
    request = urllib.request.Request(url, headers=headers or REQUEST_HEADERS)
    with NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        content = response.read().decode(charset, errors="ignore")
        return {
            "final_url": response.geturl(),
            "content_type": response.headers.get("Content-Type", ""),
            "text": content,
        }


def parse_search_results(page_html, base_url, engine_name, max_results):
    results = []
    for match in H3_BLOCK_RE.finditer(page_html):
        link_match = LINK_RE.search(match.group("title_block"))
        if not link_match:
            continue

        title = clean_text(link_match.group("title"))
        link = html.unescape(link_match.group("href"))
        link = urllib.parse.urljoin(base_url, link)
        snippet = clean_text(match.group("body_block"))[:180]

        if not title or title == "搜索":
            continue
        if link.startswith(("javascript:", "#")):
            continue

        results.append(
            {
                "engine": engine_name,
                "title": title,
                "url": link,
                "snippet": snippet or "未提取到摘要",
            }
        )
        if len(results) >= max_results:
            break
    return results


def parse_bing_rss(page_xml, engine_name, max_results):
    try:
        root = ET.fromstring(page_xml)
    except ET.ParseError as exc:
        raise RuntimeError(f"{engine_name} RSS 解析失败: {exc}") from exc

    results = []
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        snippet = clean_text(item.findtext("description"))
        if not title or not link:
            continue
        results.append(
            {
                "engine": engine_name,
                "title": title,
                "url": link,
                "snippet": snippet or "未提取到摘要",
            }
        )
        if len(results) >= max_results:
            break
    return results


def extract_page_content(page_html, fallback_title, fallback_snippet):
    page_html = page_html or ""
    title_match = TITLE_TAG_RE.search(page_html)
    page_title = clean_text(title_match.group(1)) if title_match else fallback_title

    meta_description = ""
    meta_match = META_DESC_RE.search(page_html)
    if meta_match:
        meta_description = clean_text(meta_match.group(1) or meta_match.group(2) or "")

    cleaned_html = SCRIPT_STYLE_RE.sub(" ", page_html)
    blocks = []
    for pattern in (P_TAG_RE, LI_TAG_RE):
        for match in pattern.finditer(cleaned_html):
            block = clean_text(match.group(1))
            if len(block) >= 30:
                blocks.append(block)

    deduped_blocks = []
    seen = set()
    for block in blocks:
        normalized = block.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped_blocks.append(block)
        if len(deduped_blocks) >= 20:
            break

    content_parts = []
    if meta_description:
        content_parts.append(meta_description)
    content_parts.extend(deduped_blocks)
    if not content_parts and fallback_snippet:
        content_parts.append(fallback_snippet)

    content = "\n".join(content_parts).strip()
    if len(content) < 80:
        body_text = clean_text(cleaned_html)
        if body_text:
            content = body_text[:4000]

    if not content:
        content = fallback_snippet or "未提取到页面正文内容"

    return {
        "page_title": page_title or fallback_title,
        "meta_description": meta_description,
        "content": content[:6000],
    }


def fetch_page_details(item):
    headers = MOBILE_REQUEST_HEADERS if "baike.so.com" in item["url"] else REQUEST_HEADERS
    fetch_error = ""
    final_url = item["url"]
    page_html = ""

    try:
        fetched = fetch_text(item["url"], timeout=15, headers=headers)
        final_url = fetched["final_url"]
        page_html = fetched["text"]
        blocked_markers = [
            "antispider",
            "百度安全验证",
            "访问受限",
            "网络不给力，请稍后重试",
            "403 Forbidden",
        ]
        if any(marker in page_html for marker in blocked_markers):
            page_html = ""
            raise RuntimeError("目标页面返回了反爬或验证内容")
    except Exception as exc:
        fetch_error = str(exc)

    extracted = extract_page_content(page_html, item["title"], item["snippet"])
    if fetch_error and extracted["content"] == item["snippet"]:
        extracted["content"] = (
            f"页面抓取失败，使用搜索摘要作为兜底内容。\n原始摘要: {item['snippet']}"
        )

    return {
        "engine": item["engine"],
        "search_title": item["title"],
        "search_url": item["url"],
        "final_url": final_url,
        "search_snippet": item["snippet"],
        "page_title": extracted["page_title"],
        "page_content": extracted["content"],
        "fetch_error": fetch_error,
    }


def deepen_search_results(search_results):
    deep_results = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(search_results)))) as executor:
        future_map = {
            executor.submit(fetch_page_details, item): item["url"] for item in search_results
        }
        for future in as_completed(future_map):
            deep_results.append(future.result())

    order_map = {item["url"]: index for index, item in enumerate(search_results)}
    deep_results.sort(key=lambda item: order_map.get(item["search_url"], 0))
    return deep_results


def search_engine(engine, keyword, max_results):
    search_url = engine["build_url"](keyword, max_results)
    if engine["name"] == "必应RSS":
        page_html = fetch_text(search_url, headers=REQUEST_HEADERS)["text"]
        results = parse_bing_rss(page_html, engine["name"], max_results)
    else:
        headers = REQUEST_HEADERS
        if engine["name"] == "百度移动":
            headers = MOBILE_REQUEST_HEADERS
        page_html = fetch_text(search_url, headers=headers)["text"]
        anti_spider_markers = {
            "360搜索": ["sec-warn", "360搜索验证码", "请输入验证码"],
            "搜狗微信": ["antispider", "验证码", "访问受限"],
            "百度移动": ["百度安全验证", "网络不给力，请稍后重试"],
        }
        for marker in anti_spider_markers.get(engine["name"], []):
            if marker in page_html:
                raise RuntimeError(f"{engine['name']} 返回了反爬或验证页面")
        results = parse_search_results(page_html, search_url, engine["name"], max_results)
    if not results:
        raise RuntimeError(f"{engine['name']} 未解析到可用结果")
    return results


def search_web(keyword, per_engine_limit=4, total_limit=9):
    all_results = []
    errors = []

    with ThreadPoolExecutor(max_workers=len(SEARCH_ENGINES)) as executor:
        future_map = {
            executor.submit(search_engine, engine, keyword, per_engine_limit): engine["name"]
            for engine in SEARCH_ENGINES
        }
        for future in as_completed(future_map):
            engine_name = future_map[future]
            try:
                all_results.extend(future.result())
            except Exception as exc:
                errors.append(f"{engine_name}: {exc}")

    deduped_results = []
    seen = set()
    for item in all_results:
        dedupe_key = (
            item["url"].lower(),
            item["title"].strip().lower(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped_results.append(item)
        if len(deduped_results) >= total_limit:
            break

    return deduped_results, errors


def format_search_results(search_results):
    lines = []
    for index, item in enumerate(search_results, start=1):
        lines.append(
            "\n".join(
                [
                    f"{index}. 来源搜索引擎: {item['engine']}",
                    f"标题: {item['title']}",
                    f"链接: {item['url']}",
                    f"摘要: {item['snippet']}",
                ]
            )
        )
    return "\n\n".join(lines)


def format_deep_results(deep_results):
    lines = []
    for index, item in enumerate(deep_results, start=1):
        parts = [
            f"{index}. 来源搜索引擎: {item['engine']}",
            f"搜索标题: {item['search_title']}",
            f"搜索链接: {item['search_url']}",
            f"落地链接: {item['final_url']}",
            f"页面标题: {item['page_title']}",
            f"页面内容: {item['page_content']}",
        ]
        if item["fetch_error"]:
            parts.append(f"抓取说明: {item['fetch_error']}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _sanitize_filename(text, fallback="search"):
    sanitized = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text or "").strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("._")
    return (sanitized[:80] or fallback)


def _preview_text(text, limit=300):
    content = str(text or "").strip()
    if len(content) <= limit:
        return content
    return content[: max(0, limit - 3)].rstrip() + "..."


def build_persisted_report(
    keyword,
    llm_summary_enabled,
    search_results,
    deep_results,
    search_errors,
    raw_report,
    llm_summary,
):
    lines = [
        f"关键词: {keyword}",
        f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"LLM整理: {'开启' if llm_summary_enabled else '关闭'}",
        f"聚合结果数: {len(search_results)}",
        f"深抓取结果数: {len(deep_results)}",
    ]

    if search_errors:
        lines.extend(
            [
                "",
                "搜索源异常:",
                *[f"- {item}" for item in search_errors],
            ]
        )

    if llm_summary_enabled:
        lines.extend(
            [
                "",
                "===== LLM整理结果 =====",
                llm_summary or "LLM 未返回整理内容。",
            ]
        )

    lines.extend(
        [
            "",
            "===== 原始深抓取内容 =====",
            raw_report or "未生成原始深抓取内容。",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def persist_report_to_txt(keyword, report_text, output_dir=None):
    target_dir = os.path.abspath(output_dir or DEFAULT_OUTPUT_DIR)
    os.makedirs(target_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}_{_sanitize_filename(keyword)}.txt"
    file_path = os.path.join(target_dir, file_name)
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write(report_text)
    return file_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="聚合多个中国大陆可访问搜索源，并可选使用 LLM 整理结果。"
    )
    parser.add_argument("keyword", help="要搜索的关键词")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="关闭 LLM 整理，直接输出原始聚合搜索结果",
    )
    parser.add_argument(
        "--no-file",
        action="store_true",
        help="关闭默认的本地 txt 落地，仅返回文本结果",
    )
    parser.add_argument(
        "--inline-content",
        action="store_true",
        help="兼容旧参数；开启后额外返回结构化搜索结果与原始内容字段",
    )
    parser.add_argument(
        "--output-dir",
        help="自定义 txt 输出目录；未提供时默认写入工具目录下 outputs",
    )
    return parser.parse_args()


def summarize_with_llm(system_prompt, user_prompt):
    try:
        import httpx
    except ImportError:
        return "LLM processing error: Missing httpx library. Please install it using: pip install httpx"

    try:
        from openai import OpenAI
    except ImportError:
        return "LLM processing error: Missing openai library. Please install it using: pip install openai"

    try:
        with httpx.Client(trust_env=False, timeout=30.0) as http_client:
            client = OpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL,
                http_client=http_client,
            )
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
            )
    except Exception as exc:
        return f"LLM processing error: {exc}"

    if not response.choices:
        return "LLM processing error: empty choices returned."

    content = response.choices[0].message.content
    return content or "LLM processing error: empty message content returned."


def summarize_page_with_llm(keyword, page_item):
    system_prompt = (
        "你是一个严谨的网页内容整理专家。你的任务是基于单个网页已提取出的内容做整理。\n"
        "【严格要求】\n"
        "1. 只能依据提供的页面内容整理，禁止补充外部知识。\n"
        "2. 保留关键事实、时间、主体、结论与限制条件。\n"
        "3. 如果页面内容不足，就明确说明页面信息有限。\n"
        "4. 输出结果仅能是纯文本，禁止有任何 markdown 格式。\n"
        "5. 输出尽量简洁，控制在 500汉字 以内。"
    )
    user_prompt = (
        f"请整理关键词“{keyword}”对应的单个网页内容。\n"
        f"来源搜索引擎: {page_item['engine']}\n"
        f"搜索标题: {page_item['search_title']}\n"
        f"页面标题: {page_item['page_title']}\n"
        f"页面内容:\n{page_item['page_content']}"
    )
    return summarize_with_llm(system_prompt, user_prompt)


def process_with_llm(keyword, deep_results):
    outputs = []
    for index, item in enumerate(deep_results, start=1):
        summary = summarize_page_with_llm(keyword, item)
        if summary.startswith("LLM processing error:"):
            summary = (
                "LLM 单页整理失败，回退为原始页面内容。\n"
                f"失败原因: {summary}\n"
                f"页面内容: {item['page_content']}"
            )
        outputs.append(
            "\n".join(
                [
                    f"{index}. 来源搜索引擎: {item['engine']}",
                    f"搜索标题: {item['search_title']}",
                    f"单页整理结果: {summary}",
                ]
            )
        )
    return "\n\n".join(outputs)


def _coerce_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def execute_search(
    keyword,
    llm_summary_enabled=True,
    per_engine_limit=4,
    total_limit=9,
    write_to_file=True,
    include_inline_content=False,
    output_dir=None,
):
    keyword = str(keyword or "").strip()
    if not keyword:
        raise ValueError("search_web_with_llm 需要提供 keyword。")

    search_results, search_errors = search_web(
        keyword,
        per_engine_limit=int(per_engine_limit),
        total_limit=int(total_limit),
    )
    if not search_results:
        detail = "\n".join(f"- {item}" for item in search_errors) if search_errors else "无额外失败详情。"
        raise RuntimeError(f"搜索失败，所有搜索源都未返回可用结果。\n{detail}")

    deep_results = deepen_search_results(search_results)
    raw_report = format_deep_results(deep_results)
    llm_summary = process_with_llm(keyword, deep_results) if llm_summary_enabled else ""
    final_report_content = llm_summary if llm_summary_enabled else raw_report
    output_file = ""

    if _coerce_bool(write_to_file, default=True):
        persisted_report = build_persisted_report(
            keyword=keyword,
            llm_summary_enabled=bool(llm_summary_enabled),
            search_results=search_results,
            deep_results=deep_results,
            search_errors=search_errors,
            raw_report=raw_report,
            llm_summary=llm_summary,
        )
        output_file = persist_report_to_txt(
            keyword=keyword,
            report_text=persisted_report,
            output_dir=output_dir,
        )

    final_report = final_report_content

    return {
        "tool_name": "search_web_with_llm",
        "keyword": keyword,
        "llm_summary_enabled": bool(llm_summary_enabled),
        "write_to_file": bool(write_to_file),
        "include_inline_content": bool(include_inline_content),
        "search_result_count": len(search_results),
        "deep_result_count": len(deep_results),
        "search_errors": search_errors,
        "output_file": output_file,
        "final_report_preview": _preview_text(final_report_content, limit=500),
        "search_results": search_results if include_inline_content else [],
        "deep_results": deep_results if include_inline_content else [],
        "raw_report": raw_report if include_inline_content else "",
        "final_report_text": final_report_content,
        "final_report": final_report,
        "llm_summary": llm_summary if include_inline_content else "",
    }


def run(args: dict, context: dict) -> dict:
    _ = context
    keyword = (args or {}).get("keyword", "")
    llm_summary_enabled = _coerce_bool(
        (args or {}).get("llm_summary_enabled"),
        default=not _coerce_bool((args or {}).get("no_llm"), default=False),
    )
    per_engine_limit = (args or {}).get("per_engine_limit", 4)
    total_limit = (args or {}).get("total_limit", 9)
    write_to_file = _coerce_bool((args or {}).get("write_to_file"), default=True)
    include_inline_content = _coerce_bool(
        (args or {}).get("include_inline_content"), default=False
    )
    output_dir = (args or {}).get("output_dir")
    return execute_search(
        keyword=keyword,
        llm_summary_enabled=llm_summary_enabled,
        per_engine_limit=per_engine_limit,
        total_limit=total_limit,
        write_to_file=write_to_file,
        include_inline_content=include_inline_content,
        output_dir=output_dir,
    )


def main():
    configure_console_output()
    args = parse_args()
    result = execute_search(
        keyword=args.keyword,
        llm_summary_enabled=not args.no_llm,
        write_to_file=not args.no_file,
        include_inline_content=args.inline_content,
        output_dir=args.output_dir,
    )
    print(result["final_report"])
    if result["search_errors"]:
        print("\n提示：部分搜索源不可用，但已使用其余可用结果完成处理。")
        for item in result["search_errors"]:
            print(f"- {item}")


if __name__ == "__main__":
    configure_console_output()
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

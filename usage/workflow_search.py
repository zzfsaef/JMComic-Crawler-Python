"""
GitHub Actions: 关键词搜索 JM 本子。

环境变量（值可以是空、或字面量「默认」，两者都按默认值处理）：
  JM_SEARCH_QUERY        搜索关键词（必填）
  JM_SEARCH_PAGE         页码，默认 1
  JM_SEARCH_ORDER_BY     排序 o，默认 mr
  JM_SEARCH_TIME         时间范围 t，默认 a
  JM_SEARCH_CATEGORY     分类，默认 0（全部）
  JM_SEARCH_SUB_CATEGORY 子分类，默认空
  JM_SEARCH_MAIN_TAG     标签 ID，默认 0
  JM_OPTION_PATH         配置文件路径（可选，由 workflow 生成）
  GITHUB_STEP_SUMMARY    存在时，把 markdown 结果追加进去

返回值：0 成功；1 参数或请求出错。
"""

import os
import traceback
from datetime import datetime

from jmcomic import JmOption, create_option

ALBUM_URL = 'https://18comic.vip/album/{}/'

# 默认值的唯一出口：空值和字面量「默认」都走这里
DEFAULTS = {
    'JM_SEARCH_PAGE': '1',
    'JM_SEARCH_ORDER_BY': 'mr',
    'JM_SEARCH_TIME': 'a',
    'JM_SEARCH_CATEGORY': '0',
    'JM_SEARCH_SUB_CATEGORY': '',
    'JM_SEARCH_MAIN_TAG': '0',
}


def env(name: str, default: str = '') -> str:
    value = (os.getenv(name, '') or '').strip()
    # workflow 的 choice 首项形如「默认（mr 最新）」，一律按默认值处理
    if value == '' or value.startswith('默认'):
        return default
    return value


def cell(value) -> str:
    """markdown 表格单元格：转义竖线、压掉换行"""
    return str(value if value is not None else '').replace('|', r'\|').replace('\n', ' ').strip()


def tag_line(tags) -> str:
    if isinstance(tags, str):
        return tags
    return ', '.join(str(t) for t in (tags or []))


def get_field(info, key):
    if hasattr(info, 'get'):
        return info.get(key)
    return getattr(info, key, None)


def category_text(info) -> str:
    names = []
    for key in ('category', 'category_sub'):
        value = get_field(info, key)
        title = value.get('title') if hasattr(value, 'get') else None
        if title and str(title) not in names:
            names.append(str(title))
    return ' / '.join(names)


def date_text(value) -> str:
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).strftime('%Y-%m-%d')
    return str(value)[:10]


# 候选列：不同 client.impl 返回的字段不同（api 有 author/category/adddate，html 有 tags），
# 只有整页里至少有一个非空值的列才会真正输出
COLUMNS = (
    ('author', '作者', lambda info: get_field(info, 'author') or ''),
    ('category', '分类', category_text),
    ('adddate', '发布', lambda info: date_text(get_field(info, 'adddate'))),
    ('tags', '标签', lambda info: tag_line(get_field(info, 'tags'))),
)


def make_client():
    option_path = env('JM_OPTION_PATH')
    option = create_option(option_path) if option_path else JmOption.default()
    return option.new_jm_client()


def build_markdown(query: str, page: int, order_by: str, time_range: str, category: str,
                   sub_category, main_tag: int, search_page) -> str:
    lines = [
        f'### 🔍 搜索：`{query}`',
        '',
        f'- 排序 `o={order_by}` ｜ 时间 `t={time_range}` ｜ 分类 `{category}`'
        + (f' / 子分类 `{sub_category}`' if sub_category else '')
        + f' ｜ `main_tag={main_tag}`',
        f'- 第 **{page}** 页',
        '',
    ]

    # 搜索车号时站点会 302 到本子详情页，这里被包成单本结果
    if search_page.is_single_album:
        album = search_page.single_album
        lines += [
            '> 🔎 关键词命中了车号，站点直接跳转到本子详情：',
            '',
            f'**{cell(album.name)}**',
            '',
            f'- 🆔 `JM{album.album_id}` ｜ 🔗 {ALBUM_URL.format(album.album_id)}',
            f'- ✍️ 作者：{cell(", ".join(album.authors or []))}',
            f'- 🏷️ 标签：{cell(tag_line(album.tags))}',
        ]
        return '\n'.join(lines)

    items = list(search_page.content)
    lines += [
        f'- 命中 **{search_page.total}** 条 ｜ 每页 **{search_page.page_size}** 条 ｜ 共 **{search_page.page_count}** 页',
        '',
    ]

    if not items:
        lines.append('_本页没有结果。_')
        return '\n'.join(lines)

    rows = []
    for aid, info in items:
        row = {'aid': aid, 'name': get_field(info, 'name') or ''}
        for key, _, extract in COLUMNS:
            row[key] = extract(info)
        rows.append(row)

    used = [(key, title) for key, title, _ in COLUMNS if any(row[key] for row in rows)]

    lines.append('| # | 本子 | 标题 |' + ''.join(f' {title} |' for _, title in used))
    lines.append('|---|------|------|' + '------|' * len(used))
    for index, row in enumerate(rows, start=1):
        cells = ''.join(f' {cell(row[key])} |' for key, _ in used)
        lines.append(
            f'| {index} | [JM{row["aid"]}]({ALBUM_URL.format(row["aid"])}) | {cell(row["name"])} |{cells}'
        )

    return '\n'.join(lines)


def write_summary(markdown: str) -> None:
    summary_path = os.getenv('GITHUB_STEP_SUMMARY', '')
    if not summary_path:
        return
    with open(summary_path, 'a', encoding='utf-8') as f:
        f.write(markdown + '\n\n')


def main() -> int:
    query = env('JM_SEARCH_QUERY')
    if not query:
        message = '### 🔍 搜索\n\n❌ 未提供关键词（`JM_SEARCH_QUERY` / workflow 输入 `QUERY`）'
        print(message)
        write_summary(message)
        return 1

    page = int(env('JM_SEARCH_PAGE', DEFAULTS['JM_SEARCH_PAGE']))
    order_by = env('JM_SEARCH_ORDER_BY', DEFAULTS['JM_SEARCH_ORDER_BY'])
    time_range = env('JM_SEARCH_TIME', DEFAULTS['JM_SEARCH_TIME'])
    category = env('JM_SEARCH_CATEGORY', DEFAULTS['JM_SEARCH_CATEGORY'])
    sub_category = env('JM_SEARCH_SUB_CATEGORY', DEFAULTS['JM_SEARCH_SUB_CATEGORY']) or None
    main_tag = int(env('JM_SEARCH_MAIN_TAG', DEFAULTS['JM_SEARCH_MAIN_TAG']))

    try:
        client = make_client()
        search_page = client.search(
            search_query=query,
            page=page,
            main_tag=main_tag,
            order_by=order_by,
            time=time_range,
            category=category,
            sub_category=sub_category,
        )
        markdown = build_markdown(query, page, order_by, time_range, category,
                                  sub_category, main_tag, search_page)
    except Exception as e:
        markdown = f'### 🔍 搜索：`{query}`\n\n❌ 搜索失败：{e}'
        print(traceback.format_exc())
        print(markdown)
        write_summary(markdown)
        return 1

    print(markdown)
    write_summary(markdown)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

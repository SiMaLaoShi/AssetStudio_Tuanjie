# -*- coding: utf-8 -*-
"""pkg-doctor 报告生成：读取 pkg.tsv，输出自包含的 pkg.html。

用法：
    python pkg.py <pkg.tsv>
    script.exe <pkg.tsv>
"""

from __future__ import unicode_literals

import csv
import datetime
import json
import sys
from os import path

try:
    from urllib.parse import quote
except ImportError:  # Python 2
    from urllib import quote

if sys.version_info.major < 3:
    reload(sys)
    sys.setdefaultencoding('utf8')


# 判定贴图是否已压缩。ASTC/ETC/ATC/EAC 都带 "TC"，PVRTC 也含 "TC"。
COMPRESSED_MARKERS = ('DXT', 'BC', 'ETC', 'ASTC', 'PVRTC', 'EAC', 'ATC')


def is_compressed(fmt):
    upper = (fmt or '').upper()
    return any(marker in upper for marker in COMPRESSED_MARKERS)


def load_rows(tsv_path):
    """读取 pkg.tsv，返回规范化后的行列表。"""
    raw_rows = []
    with open(tsv_path, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle, delimiter='\t'):
            if not row.get('Type'):
                continue
            raw_rows.append(row)

    rows = []
    for row in raw_rows:
        item = {
            'name': (row.get('Name') or '').replace('\x00', ''),
            'container': (row.get('Container') or '').replace('\\', '/'),
            'type': row.get('Type') or '',
            'dim': row.get('Dimension') or '',
            'format': row.get('Format') or '',
            'size': _to_int(row.get('Size')),
            'file': (row.get('FileName') or '').replace('\\', '/'),
            'hash': row.get('Hash') or '',
            'original': _short_original(row.get('OriginalFile') or ''),
            'wrap': row.get('WrapMode') or '',
        }
        if item['container'].startswith('assets/'):
            item['container'] = item['container'][7:]
        rows.append(item)
    return rows


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _short_original(value):
    value = value.replace('\\', '/')
    if 'app/Data/' in value:
        value = value[value.find('app/Data/') + 9:]
    elif '/assets/assets/' in value:
        value = value.split('/assets/assets/', 1)[1]
    elif 'assets/bin/Data' in value:
        value = 'bin/Data' + value.split('assets/bin/Data', 1)[1]
    return value


def dedup_key(row):
    """内容指纹：优先用 MD5，缺失时退化为字段组合。"""
    if row['hash']:
        return row['hash']
    return '|'.join((row['name'], row['type'], row['dim'], row['format'], str(row['size'])))


def group_assets(rows):
    """按内容指纹分组。每组记录成员、可省字节、代表行。"""
    groups = {}
    for row in rows:
        groups.setdefault(dedup_key(row), []).append(row)

    result = []
    for items in groups.values():
        sizes = [item['size'] for item in items]
        # 保留最小的一份，其余即冗余。同组尺寸通常一致，取差值之和最贴近真实可省量。
        wasted = sum(sizes) - min(sizes)
        result.append({
            'items': items,
            'wasted': wasted,
            'count': len(items),
            'row': items[0],
        })
    result.sort(key=lambda g: g['wasted'], reverse=True)
    return result


def build_categories(rows, groups):
    """按资源类型汇总数量与体积，并折算该类型下的冗余体积。"""
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(row['type'], {'type': row['type'], 'count': 0, 'bytes': 0, 'wasted': 0})
        bucket['count'] += 1
        bucket['bytes'] += row['size']

    for group in groups:
        if group['count'] < 2:
            continue
        buckets[group['row']['type']]['wasted'] += group['wasted']

    return sorted(buckets.values(), key=lambda b: b['bytes'], reverse=True)


def thumb(row):
    """缩略图相对路径，做 URL 编码（文件名含空格与 #）。"""
    if not row['file']:
        return ''
    return '/'.join(quote(part) for part in row['file'].split('/'))


def render_html(input_path, rows, groups, categories, out_path):
    total_bytes = sum(row['size'] for row in rows)
    total_wasted = sum(group['wasted'] for group in groups if group['count'] >= 2)
    dup_groups = [group for group in groups if group['count'] >= 2]

    textures = [row for row in rows if row['type'] == 'Texture2D']
    uncompressed = sorted(
        (row for row in textures if row['format'] and not is_compressed(row['format'])),
        key=lambda r: r['size'], reverse=True,
    )
    large = sorted(
        (row for row in textures if any(d in row['dim'] for d in ('1024', '2048', '4096'))),
        key=lambda r: r['size'], reverse=True,
    )
    uncompressed_bytes = sum(row['size'] for row in uncompressed)

    payload = {
        'meta': {
            'input': input_path,
            'generated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'assetCount': len(rows),
            'totalBytes': total_bytes,
            'wastedBytes': total_wasted,
            'dupGroupCount': len(dup_groups),
            'textureBytes': sum(row['size'] for row in textures),
            'textureCount': len(textures),
            'uncompressedBytes': uncompressed_bytes,
            'uncompressedCount': len(uncompressed),
            'compressedBytes': sum(row['size'] for row in textures) - uncompressed_bytes,
            'compressedCount': len(textures) - len(uncompressed),
        },
        'categories': categories,
        'dups': [_dup_row(group) for group in dup_groups],
        'uncompressed': [_texture_row(row) for row in uncompressed],
        'large': [_texture_row(row) for row in large],
        'assets': [
            {
                'name': row['name'], 'type': row['type'], 'size': row['size'],
                'dim': row['dim'], 'format': row['format'],
                'container': row['container'], 'original': row['original'],
            }
            for row in sorted(rows, key=lambda r: r['size'], reverse=True)
        ],
    }

    template = TEMPLATE.replace('/*__DATA__*/', _json_for_script(payload))
    template = template.replace('__TITLE__', _escape(input_path))
    with open(out_path, 'w', encoding='utf-8') as handle:
        handle.write(template)


def _dup_row(group):
    row = group['row']
    return {
        'name': row['name'],
        'type': row['type'],
        'size': row['size'],
        'count': group['count'],
        'wasted': group['wasted'],
        'dim': row['dim'],
        'format': row['format'],
        'thumb': thumb(row),
        'containers': [item['container'] for item in group['items']],
        'originals': sorted(set(item['original'] for item in group['items'])),
    }


def _texture_row(row):
    return {
        'name': row['name'], 'size': row['size'], 'dim': row['dim'],
        'format': row['format'], 'thumb': thumb(row),
        'container': row['container'], 'wrap': row['wrap'],
    }


def _json_for_script(payload):
    # JSON 位于 <script type="application/json"> 内，须避免出现 </script 序列。
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def _escape(value):
    return (value.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pkg-doctor · __TITLE__</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --ink:#1f2328; --muted:#6b7280;
  --accent:#ff6a00; --accent-soft:#fff1e6; --link:#0969da;
  --bar:#3b82f6; --warn:#dc2626; --ok:#16a34a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",Roboto,sans-serif}
header{background:linear-gradient(135deg,#ff6a00,#ff9147);color:#fff;padding:22px 28px}
header h1{margin:0 0 4px;font-size:20px;font-weight:600}
header .path{font-size:12px;opacity:.9;word-break:break-all}
header .time{font-size:12px;opacity:.8;margin-top:2px}
main{max-width:1500px;margin:0 auto;padding:20px 28px 60px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  margin-bottom:18px;overflow:hidden}
section>h2{margin:0;padding:14px 18px;font-size:15px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:10px;background:#fbfcfd}
section>h2 .hint{font-weight:400;font-size:12px;color:var(--muted)}
section>.body{padding:16px 18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.card .label{font-size:12px;color:var(--muted);margin-bottom:6px}
.card .value{font-size:24px;font-weight:600;letter-spacing:-.5px}
.card .sub{font-size:12px;color:var(--muted);margin-top:4px}
.card.hot{border-color:#f5c9a8;background:var(--accent-soft)}
.card.hot .value{color:var(--accent)}
.bars{display:flex;flex-direction:column;gap:8px;margin-top:16px}
.bar-row{display:grid;grid-template-columns:150px 1fr 110px 78px;align-items:center;gap:10px;font-size:13px}
.bar-row .name{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-row .track{background:#eef1f5;border-radius:5px;height:18px;overflow:hidden;display:flex}
.bar-row .fill{background:var(--bar);height:100%}
.bar-row .fill.wasted{background:var(--accent)}
.bar-row .num{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.bar-row .num.strong{color:var(--ink);font-weight:600}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
input[type=search],select{padding:6px 10px;border:1px solid var(--line);border-radius:6px;
  font:inherit;background:#fff;color:inherit}
input[type=search]{min-width:260px}
.toolbar .count{font-size:12px;color:var(--muted);margin-left:auto}
.table-wrap{overflow:auto;max-height:640px;border:1px solid var(--line);border-radius:8px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
thead th{position:sticky;top:0;background:#fbfcfd;border-bottom:1px solid var(--line);
  padding:9px 10px;text-align:left;font-weight:600;white-space:nowrap;cursor:pointer;z-index:2}
thead th:hover{background:#f2f5f8}
thead th .arrow{color:var(--accent);font-size:11px}
tbody td{border-bottom:1px solid #f0f2f5;padding:8px 10px;vertical-align:top}
tbody tr:hover{background:#fafbfc}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
td.name{min-width:200px;word-break:break-word}
td.paths{min-width:220px;max-width:420px;word-break:break-all;color:var(--muted);font-size:12px}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;background:#eef1f5;
  font-size:11px;color:var(--muted);white-space:nowrap}
.tag.T{background:#e8f0fe;color:#1a56db}
.tag.S{background:#fce7f3;color:#be185d}
.tag.M{background:#e0f2e9;color:#15803d}
.tag.A{background:#fef3c7;color:#b45309}
.tag.X{background:#ede9fe;color:#6d28d9}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
  background:var(--accent-soft);color:var(--accent);font-weight:600}
.thumb{width:64px;height:64px;object-fit:contain;background:
  repeating-conic-gradient(#e9edf2 0 25%,#fff 0 50%) 0 0/12px 12px;
  border:1px solid var(--line);border-radius:5px;cursor:zoom-in;display:block}
.pager{display:flex;gap:6px;align-items:center;justify-content:center;padding:10px;font-size:12px;color:var(--muted)}
.pager button{padding:4px 10px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font:inherit}
.pager button:disabled{opacity:.45;cursor:default}
#lightbox{position:fixed;inset:0;background:rgba(15,18,22,.82);display:none;
  align-items:center;justify-content:center;z-index:99;cursor:zoom-out}
#lightbox img{max-width:92vw;max-height:92vh;background:#fff;border-radius:8px}
#lightbox.on{display:flex}
.empty{padding:24px;text-align:center;color:var(--muted)}
nav{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
nav .inner{max-width:1500px;margin:0 auto;padding:8px 28px;display:flex;
  gap:4px;overflow-x:auto;align-items:center}
nav a{color:var(--muted);text-decoration:none;padding:6px 12px;border-radius:99px;
  font-size:13px;white-space:nowrap;border:1px solid transparent}
nav a:hover{color:var(--ink);background:#f1f4f7}
nav a.on{color:var(--accent);background:var(--accent-soft);border-color:#f5c9a8;font-weight:600}
nav a .n{color:var(--muted);font-size:11px;font-weight:400;margin-left:4px}
nav a.on .n{color:var(--accent)}
section{scroll-margin-top:56px}
#totop{position:fixed;right:22px;bottom:22px;width:40px;height:40px;border-radius:50%;
  border:1px solid var(--line);background:#fff;color:var(--muted);cursor:pointer;
  font-size:17px;line-height:1;display:none;place-items:center;box-shadow:0 2px 10px rgba(0,0,0,.1)}
#totop.on{display:grid}
#totop:hover{color:var(--accent);border-color:#f5c9a8}
</style>
</head>
<body>
<header>
  <h1>pkg-doctor 包体分析</h1>
  <div class="path">__TITLE__</div>
  <div class="time" id="generated"></div>
</header>
<nav><div class="inner" id="nav"></div></nav>
<main>
  <div class="cards" id="cards"></div>

  <section id="sec-types">
    <h2>资源类型分布 <span class="hint">橙色为该类型中重复入包、可减去的部分</span></h2>
    <div class="body"><div class="bars" id="bars"></div></div>
  </section>

  <section id="sec-dups">
    <h2>重复入包 <span class="hint">相同内容被多次打进包体，删除多余副本可减去的体积</span></h2>
    <div class="body">
      <div class="toolbar">
        <input type="search" id="dup-q" placeholder="筛选名称 / 路径 / 格式…">
        <select id="dup-type"></select>
        <span class="count" id="dup-count"></span>
      </div>
      <div class="table-wrap"><table id="dup-table"></table></div>
      <div class="pager" id="dup-pager"></div>
    </div>
  </section>

  <section id="sec-unc">
    <h2>未压缩贴图 <span class="hint">建议改用 ASTC / ETC2 等压缩格式</span></h2>
    <div class="body">
      <div class="toolbar">
        <input type="search" id="unc-q" placeholder="筛选名称 / 路径 / 格式…">
        <span class="count" id="unc-count"></span>
      </div>
      <div class="table-wrap"><table id="unc-table"></table></div>
      <div class="pager" id="unc-pager"></div>
    </div>
  </section>

  <section id="sec-big">
    <h2>大尺寸贴图 <span class="hint">边长 ≥1024，优先确认是否需要这么高分辨率</span></h2>
    <div class="body">
      <div class="toolbar">
        <input type="search" id="big-q" placeholder="筛选名称 / 路径 / 格式…">
        <span class="count" id="big-count"></span>
      </div>
      <div class="table-wrap"><table id="big-table"></table></div>
      <div class="pager" id="big-pager"></div>
    </div>
  </section>

  <section id="sec-all">
    <h2>全部资源 <span class="hint">按体积降序，可筛选排序</span></h2>
    <div class="body">
      <div class="toolbar">
        <input type="search" id="all-q" placeholder="筛选名称 / 路径 / 类型…">
        <select id="all-type"></select>
        <span class="count" id="all-count"></span>
      </div>
      <div class="table-wrap"><table id="all-table"></table></div>
      <div class="pager" id="all-pager"></div>
    </div>
  </section>
</main>
<button id="totop" title="回到顶部">↑</button>
<div id="lightbox"><img alt=""></div>

<script id="payload" type="application/json">/*__DATA__*/</script>
<script>
(function(){
  "use strict";
  var D = JSON.parse(document.getElementById('payload').textContent);

  function esc(s){
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }
  function bytes(n){
    if(n < 1024) return n + ' B';
    var u = ['KB','MB','GB','TB'], i = -1;
    do { n /= 1024; i++; } while(n >= 1024 && i < u.length - 1);
    return (n >= 100 ? n.toFixed(0) : n.toFixed(1)) + ' ' + u[i];
  }
  function pct(part, whole){ return whole > 0 ? (part * 100 / whole).toFixed(1) + '%' : '0%'; }

  // ── 概览卡片 ────────────────────────────────────────────────
  var m = D.meta;
  document.getElementById('generated').textContent = '生成于 ' + m.generated;
  // 未压缩贴图若统一转 ASTC，按 24bpp 原图对比 ASTC 位率换算可省体积。
  var astcSave = m.uncompressedBytes - m.uncompressedBytes / 6.74; // ASTC_RGB_6x6
  document.getElementById('cards').innerHTML = [
    ['资产总体积', bytes(m.totalBytes), m.assetCount + ' 个资源', ''],
    ['重复可减去', bytes(m.wastedBytes), m.dupGroupCount + ' 组重复 · ' + pct(m.wastedBytes, m.totalBytes), 'hot'],
    ['未压缩贴图', bytes(m.uncompressedBytes), m.uncompressedCount + ' 张 · 转 ASTC_6x6 可省 ' + bytes(astcSave), 'hot'],
    ['贴图合计', bytes(m.textureBytes), m.textureCount + ' 张 · 占 ' + pct(m.textureBytes, m.totalBytes), ''],
    ['已压缩贴图', bytes(m.compressedBytes), m.compressedCount + ' 张', '']
  ].map(function(c){
    return '<div class="card ' + c[3] + '"><div class="label">' + c[0] +
           '</div><div class="value">' + c[1] + '</div><div class="sub">' + c[2] + '</div></div>';
  }).join('');

  // ── 类型分布条 ──────────────────────────────────────────────
  var maxBytes = D.categories.length ? D.categories[0].bytes : 1;
  document.getElementById('bars').innerHTML = D.categories.map(function(c){
    var solid = c.bytes - c.wasted;
    return '<div class="bar-row">' +
      '<div class="name" title="' + esc(c.type) + '">' + esc(c.type) + '</div>' +
      '<div class="track" title="总量 ' + bytes(c.bytes) + '，其中重复 ' + bytes(c.wasted) + '">' +
        '<div class="fill" style="width:' + (solid * 100 / maxBytes).toFixed(2) + '%"></div>' +
        '<div class="fill wasted" style="width:' + (c.wasted * 100 / maxBytes).toFixed(2) + '%"></div>' +
      '</div>' +
      '<div class="num strong">' + bytes(c.bytes) + '</div>' +
      '<div class="num">' + pct(c.bytes, m.totalBytes) + '</div>' +
    '</div>';
  }).join('');

  var TYPE_TAG = {Texture2D:'T', Shader:'S', Mesh:'M', AudioClip:'A', AnimationClip:'X'};
  function tag(t){
    var k = TYPE_TAG[t] || 'X';
    return '<span class="tag ' + k + '">' + esc(t) + '</span>';
  }
  function thumbCell(url){
    return url ? '<img class="thumb" loading="lazy" src="' + esc(url) + '" alt="">' : '';
  }
  function multi(list){
    if(!list || !list.length) return '';
    return list.map(function(x){ return x ? esc(x) : '<span class="tag">(无)</span>'; }).join('<br>');
  }

  // ── 通用可排序表格 ──────────────────────────────────────────
  function makeTable(cfg){
    var rows = cfg.rows.slice();
    var sortKey = cfg.defaultSort[0], sortDir = cfg.defaultSort[1];

    var table = document.getElementById(cfg.tableId);
    var pager = document.getElementById(cfg.pagerId);
    var counter = document.getElementById(cfg.countId);
    var query = document.getElementById(cfg.queryId);
    var typeSel = cfg.typeId ? document.getElementById(cfg.typeId) : null;

    if(typeSel){
      var types = [];
      cfg.rows.forEach(function(r){ if(types.indexOf(r.type) < 0) types.push(r.type); });
      types.sort();
      typeSel.innerHTML = '<option value="">全部类型</option>' +
        types.map(function(t){ return '<option>' + esc(t) + '</option>'; }).join('');
    }

    var page = 0, pageSize = cfg.pageSize || 200;

    function filtered(){
      var q = (query && query.value || '').trim().toLowerCase();
      var wantType = typeSel && typeSel.value;
      return rows.filter(function(r){
        if(wantType && r.type !== wantType) return false;
        if(!q) return true;
        return cfg.searchText(r).toLowerCase().indexOf(q) >= 0;
      });
    }
    function sorted(list){
      var dir = sortDir === 'asc' ? 1 : -1;
      return list.slice().sort(function(a, b){
        var va = a[sortKey], vb = b[sortKey];
        if(typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
        return String(va).localeCompare(String(vb)) * dir;
      });
    }
    function arrow(key){
      return key === sortKey ? ' <span class="arrow">' + (sortDir === 'asc' ? '▲' : '▼') + '</span>' : '';
    }

    function render(){
      var list = filtered();
      if(counter) counter.textContent = '共 ' + list.length + ' 条' +
        (list.length !== rows.length ? '（已筛选，全部 ' + rows.length + ' 条）' : '');
      if(!list.length){
        table.innerHTML = '<tbody><tr><td class="empty">没有匹配的结果</td></tr></tbody>';
        pager.innerHTML = '';
        return;
      }
      list = sorted(list);
      var pages = Math.ceil(list.length / pageSize);
      if(page >= pages) page = pages - 1;
      if(page < 0) page = 0;
      var slice = list.slice(page * pageSize, page * pageSize + pageSize);

      var head = '<thead><tr>' + cfg.columns.map(function(c){
        return '<th data-key="' + c.key + '">' + esc(c.title) + arrow(c.key) + '</th>';
      }).join('') + '</tr></thead>';
      var body = '<tbody>' + slice.map(function(r){
        return '<tr>' + cfg.columns.map(function(c){
          return '<td class="' + (c.cls || '') + '">' + c.render(r) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody>';
      table.innerHTML = head + body;

      Array.prototype.forEach.call(table.querySelectorAll('thead th'), function(th){
        th.addEventListener('click', function(){
          var k = th.getAttribute('data-key');
          if(k === sortKey) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
          else { sortKey = k; sortDir = (cfg.numeric.indexOf(k) >= 0) ? 'desc' : 'asc'; }
          page = 0;
          render();
        });
      });

      pager.innerHTML = pages > 1
        ? '<button ' + (page === 0 ? 'disabled' : '') + ' data-go="0">首页</button>' +
          '<button ' + (page === 0 ? 'disabled' : '') + ' data-go="' + (page - 1) + '">上一页</button>' +
          ' <span>第 ' + (page + 1) + ' / ' + pages + ' 页</span> ' +
          '<button ' + (page >= pages - 1 ? 'disabled' : '') + ' data-go="' + (page + 1) + '">下一页</button>' +
          '<button ' + (page >= pages - 1 ? 'disabled' : '') + ' data-go="' + (pages - 1) + '">末页</button>'
        : '';
      Array.prototype.forEach.call(pager.querySelectorAll('button'), function(btn){
        btn.addEventListener('click', function(){
          page = parseInt(btn.getAttribute('data-go'), 10) || 0;
          render();
        });
      });
    }

    if(query) query.addEventListener('input', function(){ page = 0; render(); });
    if(typeSel) typeSel.addEventListener('change', function(){ page = 0; render(); });
    render();
    return render;
  }

  var amount = [
    {key:'name', title:'名称', cls:'name', render:function(r){ return esc(r.name); }},
    {key:'type', title:'类型', render:function(r){ return tag(r.type); }}
  ];

  makeTable({
    tableId:'dup-table', pagerId:'dup-pager', countId:'dup-count', queryId:'dup-q', typeId:'dup-type',
    rows:D.dups, defaultSort:['wasted','desc'], numeric:['size','count','wasted'],
    searchText:function(r){ return r.name + ' ' + r.format + ' ' + r.dim + ' ' + r.containers.join(' '); },
    columns:[
      {key:'name', title:'名称', cls:'name', render:function(r){ return esc(r.name); }},
      {key:'type', title:'类型', render:function(r){ return tag(r.type); }},
      {key:'wasted', title:'可减去', cls:'num', render:function(r){ return '<span class="pill">' + bytes(r.wasted) + '</span>'; }},
      {key:'size', title:'单份', cls:'num', render:function(r){ return bytes(r.size); }},
      {key:'count', title:'份数', cls:'num', render:function(r){ return r.count; }},
      {key:'dim', title:'尺寸 / 格式', render:function(r){
        return esc(r.dim) + (r.format ? '<br><span class="tag">' + esc(r.format) + '</span>' : ''); }},
      {key:'thumb', title:'预览', render:function(r){ return thumbCell(r.thumb); }},
      {key:'containers', title:'引用它的资源', cls:'paths', render:function(r){ return multi(r.containers); }},
      {key:'originals', title:'来自', cls:'paths', render:function(r){ return multi(r.originals); }}
    ]
  });

  makeTable({
    tableId:'unc-table', pagerId:'unc-pager', countId:'unc-count', queryId:'unc-q',
    rows:D.uncompressed, defaultSort:['size','desc'], numeric:['size'],
    searchText:function(r){ return r.name + ' ' + r.format + ' ' + r.dim + ' ' + r.container; },
    columns:[
      {key:'name', title:'名称', cls:'name', render:function(r){ return esc(r.name); }},
      {key:'size', title:'体积', cls:'num', render:function(r){ return bytes(r.size); }},
      {key:'dim', title:'尺寸', cls:'num', render:function(r){ return esc(r.dim); }},
      {key:'format', title:'格式', render:function(r){ return '<span class="tag">' + esc(r.format) + '</span>'; }},
      {key:'wrap', title:'Wrap', render:function(r){ return esc(r.wrap); }},
      {key:'thumb', title:'预览', render:function(r){ return thumbCell(r.thumb); }},
      {key:'container', title:'引用它的资源', cls:'paths', render:function(r){ return esc(r.container); }}
    ]
  });

  makeTable({
    tableId:'big-table', pagerId:'big-pager', countId:'big-count', queryId:'big-q',
    rows:D.large, defaultSort:['size','desc'], numeric:['size'],
    searchText:function(r){ return r.name + ' ' + r.format + ' ' + r.dim + ' ' + r.container; },
    columns:[
      {key:'name', title:'名称', cls:'name', render:function(r){ return esc(r.name); }},
      {key:'size', title:'体积', cls:'num', render:function(r){ return bytes(r.size); }},
      {key:'dim', title:'尺寸', cls:'num', render:function(r){ return esc(r.dim); }},
      {key:'format', title:'格式', render:function(r){ return '<span class="tag">' + esc(r.format) + '</span>'; }},
      {key:'thumb', title:'预览', render:function(r){ return thumbCell(r.thumb); }},
      {key:'container', title:'引用它的资源', cls:'paths', render:function(r){ return esc(r.container); }}
    ]
  });

  makeTable({
    tableId:'all-table', pagerId:'all-pager', countId:'all-count', queryId:'all-q', typeId:'all-type',
    rows:D.assets, defaultSort:['size','desc'], numeric:['size'], pageSize:200,
    searchText:function(r){ return r.name + ' ' + r.type + ' ' + r.format + ' ' + r.container; },
    columns:[
      {key:'name', title:'名称', cls:'name', render:function(r){ return esc(r.name); }},
      {key:'type', title:'类型', render:function(r){ return tag(r.type); }},
      {key:'size', title:'体积', cls:'num', render:function(r){ return bytes(r.size); }},
      {key:'dim', title:'尺寸', cls:'num', render:function(r){ return esc(r.dim); }},
      {key:'format', title:'格式', render:function(r){ return r.format ? '<span class="tag">' + esc(r.format) + '</span>' : ''; }},
      {key:'container', title:'引用它的资源', cls:'paths', render:function(r){ return esc(r.container); }},
      {key:'original', title:'来自', cls:'paths', render:function(r){ return esc(r.original); }}
    ]
  });

  // ── 顶部导航 ────────────────────────────────────────────────
  var NAV = [
    {id:'sec-types', label:'资源类型', n:D.categories.length + ' 类'},
    {id:'sec-dups',  label:'重复入包', n:D.dups.length + ' 组 / ' + bytes(m.wastedBytes)},
    {id:'sec-unc',   label:'未压缩贴图', n:D.uncompressed.length + ' 张 / ' + bytes(m.uncompressedBytes)},
    {id:'sec-big',   label:'大尺寸贴图', n:D.large.length + ' 张'},
    {id:'sec-all',   label:'全部资源', n:m.assetCount + ' 个'}
  ];
  var nav = document.getElementById('nav');
  nav.innerHTML = NAV.map(function(s){
    return '<a href="#' + s.id + '" data-target="' + s.id + '">' + esc(s.label) +
           '<span class="n">' + esc(s.n) + '</span></a>';
  }).join('');
  var navLinks = Array.prototype.slice.call(nav.querySelectorAll('a'));
  var sections = NAV.map(function(s){ return document.getElementById(s.id); });

  nav.addEventListener('click', function(e){
    var a = e.target.closest ? e.target.closest('a') : null;
    if(!a) return;
    e.preventDefault();
    var el = document.getElementById(a.getAttribute('data-target'));
    if(el) el.scrollIntoView({behavior:'smooth', block:'start'});
    history.replaceState(null, '', a.getAttribute('href'));
  });

  var totop = document.getElementById('totop');
  function onScroll(){
    totop.classList.toggle('on', window.scrollY > 400);
    // 当前视口顶部以下最后一个已进入的 section 即当前模块
    var idx = 0;
    for(var i = 0; i < sections.length; i++){
      if(sections[i] && sections[i].getBoundingClientRect().top <= 80) idx = i;
    }
    if(window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) idx = sections.length - 1;
    navLinks.forEach(function(a, i){ a.classList.toggle('on', i === idx); });
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  window.addEventListener('resize', onScroll);
  onScroll();

  totop.addEventListener('click', function(){
    window.scrollTo({top:0, behavior:'smooth'});
  });

  // ── 预览放大 ────────────────────────────────────────────────
  var box = document.getElementById('lightbox');
  var boxImg = box.querySelector('img');
  document.addEventListener('click', function(e){
    if(e.target.classList && e.target.classList.contains('thumb')){
      boxImg.src = e.target.src;
      box.classList.add('on');
    } else if(e.target === box || e.target === boxImg){
      box.classList.remove('on');
      boxImg.src = '';
    }
  });
  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape'){ box.classList.remove('on'); boxImg.src = ''; }
  });
})();
</script>
</body>
</html>
"""


def main():
    tsv_path = 'pkg.tsv'
    if len(sys.argv) > 1:
        tsv_path = sys.argv[1]

    if not path.exists(tsv_path):
        sys.stderr.write('找不到输入文件：%s\n' % tsv_path)
        return 1

    rows = load_rows(tsv_path)
    if not rows:
        sys.stderr.write('输入文件没有有效数据行：%s\n' % tsv_path)
        return 1

    groups = group_assets(rows)
    categories = build_categories(rows, groups)
    out_path = path.join(path.dirname(path.abspath(tsv_path)), 'pkg.html')
    render_html(tsv_path, rows, groups, categories, out_path)

    print('\nreport -> %s\n' % out_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())

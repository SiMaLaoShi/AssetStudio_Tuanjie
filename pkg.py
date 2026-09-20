# -*- en coding: utf-8 -*-

from __future__ import unicode_literals
import sys
import csv
import json
from io import open
from os import path
from collections import OrderedDict

if sys.version_info.major < 3:
    reload(sys)
    sys.setdefaultencoding('utf8')

markdeep_head = """
<meta charset="utf-8" emacsmode="-*- markdown -*-">
<link rel="stylesheet" href="https://casual-effects.com/markdeep/latest/newsmag.css?"">
<script>markdeepOptions={tocStyle:'medium'};</script>
<script src="https://casual-effects.com/markdeep/markdeep.min.js?" charset="utf-8"></script>
<style>
.md h1 {
    color: #ff6600;  
}
.md div.title {
    background-color: #ff6600;  
}
</style>

"""

MAX_ROWs_PRINTED = 100

def pretty_number(num):
    if num < 1e3:
        return str(num)
    if num < 1e6:
        return "%.1fK" % (num/1e3)
    if num < 1e9:
        return "%.1fM" % (num/1e6)
    if num < 1e12:
        return "%.1fG" % (num/1e9)
    return str(num)

def process_pkg_csv(filename):
    assets = {}
    dir_name = path.dirname(filename)
    # print(filename, dir_name)

    pkg_html = path.join(dir_name,'pkg.html')
    markdown = open(pkg_html, 'w', encoding='utf-8')
    markdown.write(markdeep_head)
    # markdown.write('# %s/n' % (self.getUniqueName()))
    with open(filename, encoding='utf-8') as infile:
        markdown.write('**pkg_doctor**\n')
        markdown.write(' %s\n' % filename)
        if 'tsv' in filename:
            try:
                reader = csv.DictReader(infile, delimiter='\t')
            except:
                reader = csv.DictReader(infile, delimiter=b'\t')
        else:
            reader = csv.DictReader(infile)
        for row in reader:
            # print(row)
            hash = row['Hash']
            filename = row['FileName']
            if row['Container'].startswith('assets/'):
                row['Container'] = row['Container'][7:]
            # row['Container'] = row['Container'].replace(' ', '_')
            OriginalFile = row['OriginalFile']
            if OriginalFile.startswith('assets/'):
                OriginalFile = OriginalFile[7:]
            elif 'app/Data/' in OriginalFile:
                idx = OriginalFile.find('app/Data/')
                OriginalFile = OriginalFile[idx + 9:]
            row['OriginalFile'] = OriginalFile
            # row['OriginalFile'] = row['OriginalFile'].replace(' ', '_')
            if not hash:
                hash = row['Name']+row['Type']+row['Dimension']+row['Format']+row['Size']
            if filename:
                file_path = path.join(dir_name, filename)
                if path.exists(file_path):
                    file_size = path.getsize(file_path)
                    hash = row['Type'] + str(file_size)
            if hash not in assets:
                assets[hash] = {
                    'wasted': 0,
                    'items': []
                }
            asset_item = assets[hash]
            row['Size'] = int(row['Size'])
            asset_item['items'].append(row)
            asset_item['wasted'] = row['Size'] * (len(asset_item['items']) - 1) 
            # print(row['Name'], md5)

    total_bytes = 1
    total_texture_bytes = 0
    total_shader_bytes = 0
    total_font_bytes = 0
    total_mesh_bytes = 0
    total_audio_bytes = 0
    total_text_bytes = 0
    total_animation_bytes = 0

    # TODO: refactor
    total_wasted_bytes = 0
    total_wasted_texture_bytes = 0
    total_wasted_shader_bytes = 0
    total_wasted_font_bytes = 0
    total_wasted_mesh_bytes = 0
    total_wasted_audio_bytes = 0
    total_wasted_text_bytes = 0
    total_wasted_animation_bytes = 0

    total_uncompressed_bytes = 0
    total_uncompressed_count = 0
    for k, v in assets.items():
        wasted_bytes = v['wasted']
        total_wasted_bytes += wasted_bytes
        items = v['items']
        row = items[0]
        items_bytes = row['Size'] * len(items)
        total_bytes += items_bytes
        if row['Type'] == 'Texture2D':
            total_texture_bytes += items_bytes
            total_wasted_texture_bytes += wasted_bytes
        elif row['Type'] == 'Shader':
            total_shader_bytes += items_bytes
            total_wasted_shader_bytes += wasted_bytes
        elif row['Type'] == 'Font':
            total_font_bytes += items_bytes
            total_wasted_font_bytes += wasted_bytes
        elif row['Type'] == 'Mesh':
            total_mesh_bytes += items_bytes
            total_wasted_mesh_bytes += wasted_bytes
        elif row['Type'] == 'AudioClip':
            total_audio_bytes += items_bytes
            total_wasted_audio_bytes += wasted_bytes
        elif row['Type'] == 'AnimationClip':
            total_animation_bytes += items_bytes
            total_wasted_animation_bytes += wasted_bytes
        elif row['Type'] == 'TextAsset':
            total_text_bytes += items_bytes
            total_wasted_text_bytes += wasted_bytes

        if row['Type'] == 'Texture2D' and 'DXT' not in row['Format'] and 'BC' not in row['Format'] and 'TC' not in row['Format']:
            total_uncompressed_bytes += items_bytes
            total_uncompressed_count += len(items)

    markdown.write('# 包体概览\n')
    markdown.write('- 对 apk 解压后的现有资产尺寸: **%s**\n' % pretty_number(total_bytes))
    if total_bytes > 0:
        markdown.write('  - Texture: **%s** (%.2f%%)\n' % (pretty_number(total_texture_bytes), total_texture_bytes * 100 / total_bytes))
        markdown.write('  - Mesh: **%s** (%.2f%%)\n' % (pretty_number(total_mesh_bytes), total_mesh_bytes * 100 / total_bytes))
        markdown.write('  - AnimationClip: **%s** (%.2f%%)\n' % (pretty_number(total_animation_bytes), total_animation_bytes * 100 / total_bytes))
        markdown.write('  - TextAsset: **%s** (%.2f%%)\n' % (pretty_number(total_text_bytes), total_text_bytes * 100 / total_bytes))
        markdown.write('  - Shader: **%s** (%.2f%%)\n' % (pretty_number(total_shader_bytes), total_shader_bytes * 100 / total_bytes))
        markdown.write('  - Font: **%s** (%.2f%%)\n' % (pretty_number(total_font_bytes), total_font_bytes * 100 / total_bytes))
        markdown.write('  - AudioClip: **%s** (%.2f%%)\n' % (pretty_number(total_audio_bytes), total_audio_bytes * 100 / total_bytes))

    markdown.write('- 其中重复入包的资产，可减去 **%s**\n' % pretty_number(total_wasted_bytes))
    if total_wasted_bytes > 0:
        markdown.write('  - Texture: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_texture_bytes), total_wasted_texture_bytes * 100 / total_wasted_bytes))
        markdown.write('  - Mesh: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_mesh_bytes), total_wasted_mesh_bytes * 100 / total_wasted_bytes))
        markdown.write('  - AnimationClip: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_animation_bytes), total_wasted_animation_bytes * 100 / total_wasted_bytes))
        markdown.write('  - TextAsset: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_text_bytes), total_wasted_text_bytes * 100 / total_wasted_bytes))
        markdown.write('  - Shader: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_shader_bytes), total_wasted_shader_bytes * 100 / total_wasted_bytes))
        markdown.write('  - Font: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_font_bytes), total_wasted_font_bytes * 100 / total_wasted_bytes))
        markdown.write('  - AudioClip: **%s** (%.2f%%)\n' % (pretty_number(total_wasted_audio_bytes), total_wasted_audio_bytes * 100 / total_wasted_bytes))

    markdown.write('- 其中未经压缩的贴图尺寸为 **%s** \n' % pretty_number(total_uncompressed_bytes))
    markdown.write('  - 若统一选用 `ASTC_RGB_4x4` 格式，可减去 **%s**\n' % pretty_number(total_uncompressed_bytes - total_uncompressed_bytes/3)) # sizeof(RGB24) / bpp(astc_4x4) = 24 / 8 = 3
    markdown.write('  - 若统一选用 `ASTC_RGB_6x6` 格式，可减去 **%s**\n' % pretty_number(total_uncompressed_bytes - total_uncompressed_bytes/6.74)) # sizeof(RGB24) / bpp(astc_6x6) = 24 / 3.56 = 6.74
    markdown.write('  - 若统一选用 `ASTC_RGB_8x8` 格式，可减去 **%s**\n' % pretty_number(total_uncompressed_bytes - total_uncompressed_bytes/12)) # sizeof(RGB24) / bpp(astc_8x8) = 24 / 2 = 12

    markdown.write('\n')

    markdown.write('# 重复入包 Top 榜\n')
    markdown.write('Name|Type|Wasted|Format|Preview|Container|OriginalFile\n')
    markdown.write('----|----|------|------|-------|---------|------------\n')
    count = 0
    for k in OrderedDict(sorted(assets.items(), key=lambda item: item[1]['wasted'], reverse=True)):
        v = assets[k]
        items = v['items']
        item_count = len(items)
        if item_count <= 1:
            # skip non-duplicated assets
            continue

        row = items[0]
        names = []
        containers = []
        originalFiles = []
        preview = ''
        for item in items:
            container = item['Container']
            if not container:
                container = '""'
            names.append(item['Name'])
            containers.append(container)
            originalFiles.append(item['OriginalFile'])
        asset_filename = row['FileName']
        if 'png' in asset_filename or 'jpeg' in asset_filename:
            preview = '![](%s border="2")' % asset_filename
        type = row['Type']
        if type == 'Texture2D':
            type = 'Texture'
        elif type == 'AnimatioClip':
            type = 'AnimClip'
        format = row['Format']
        if 'Crunched' in format:
            format = format.replace('Crunched', '')
        markdown.write('%s|%s|%s|%s|%s|%s|%s\n' % (
            '<br>'.join(names),
            '%s<br>%s%s' % (type, pretty_number(row['Size']), '*%d'% item_count if item_count > 1 else ''),
            '**%s**' % pretty_number(v['wasted']),
            '%s<br>%s' % (row['Dimension'], format),
            preview,
            '<br>'.join(containers),
            '<br>'.join(originalFiles),
        ))
        count += 1
        if count > MAX_ROWs_PRINTED:
            break            
    markdown.write('\n')

    markdown.write('# 未压缩贴图 Top 榜\n')
    markdown.write('Name|Size|Dimension|Format|Preview|Container\n')
    markdown.write('----|----|---------|------|-------|---------\n')
    count = 0
    for k in OrderedDict(sorted(assets.items(), key=lambda item: item[1]['items'][0]['Size'], reverse=True)):        
        v = assets[k]    
        items = v['items']
        item_count = len(items)
        row = items[0]
        if row['Type'] != 'Texture2D':
            continue
        format = row['Format']
        if 'DXT' in format or 'BC' in format or 'TC' in format:
        # or 'Alpha8' in format:
            continue
        asset_name = row['Name']
        asset_filename = row['FileName']
        if 'xdsdk' in asset_name or 'taptap' in asset_name or 'UnityWatermark' in asset_name:
            # from SDK
            continue
        
        if 'png' in asset_filename or 'jpeg' in asset_filename:
            preview = '![](%s border="2")' % asset_filename
        else:
            preview = ''   
        markdown.write('%s|%s|%s|%s|%s|%s\n' % (
            row['Name'],
            '%s%s' % (pretty_number(row['Size']), '*%d'% item_count if item_count > 1 else ''),
            row['Dimension'],
            row['Format'],
            preview,
            row['Container'],
        ))

        count += 1
        if count > MAX_ROWs_PRINTED:
            break
    markdown.write('\n')

    markdown.write('# 大尺寸贴图 Top 榜\n')
    markdown.write('Name|Size|Dimension|Format|Preview|Container\n')
    markdown.write('----|----|---------|------|-------|---------\n')
    count = 0
    for k in OrderedDict(sorted(assets.items(), key=lambda item: item[1]['items'][0]['Size'], reverse=True)):
        v = assets[k]    
        items = v['items']
        row = items[0]
        if row['Type'] != 'Texture2D':
            continue
        dimension = row['Dimension']
        if '1024' not in dimension and '2048' not in dimension and '4096' not in dimension:
            continue

        asset_name = row['Name']
        asset_filename = row['FileName']
        if '_1024' in asset_name or '_2048' in asset_name or 'sactx' in asset_name or 'lightmap' in asset_name.lower():
            continue
        if 'png' in asset_filename or 'jpeg' in asset_filename:
            preview = '![](%s border="2")' % asset_filename
        else:
            preview = ''   
        markdown.write('%s|%s|%s|%s|%s|%s\n' % (
            row['Name'],
            pretty_number(row['Size']),
            row['Dimension'],
            row['Format'],
            preview,
            row['Container'],
        ))
        count += 1
        if count > MAX_ROWs_PRINTED:
            break
    markdown.write('\n')

    print('\nreport -> %s\n' % pkg_html)

if __name__ == '__main__':
    pkg_csv = 'c:/svn_pool/pkg-doctor/_t3_0628/Daily_20210663c4e5.1624845360-pkg/pkg.tsv'
    if len(sys.argv) > 1:
        pkg_csv = sys.argv[1]    
    process_pkg_csv(pkg_csv)
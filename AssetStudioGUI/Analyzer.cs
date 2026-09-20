using AssetStudio;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace AssetStudioGUI
{
    /// <summary>
    /// 包体分析：把资源清单导出为 pkg.tsv，供 pkg.py 生成报告。
    /// 逻辑自 pkg-doctor 的 Studio.ExportAssets2 / ExportVizFile 移植而来。
    /// </summary>
    internal static class Analyzer
    {
        private static readonly string[] WrapModes = { "Repeat", "Clamp" };

        public static void ExportPackage(string savePath, List<AssetItem> toExportAssets, StreamWriter csvFile)
        {
            Thread.CurrentThread.CurrentCulture = new CultureInfo("en-US");


            csvFile.Write("Name\tContainer\tType\tDimension\tFormat\tSize\tFileName\tHash\tOriginalFile\tWrapMode\n");

            var toExportCount = toExportAssets.Count;
            var exportedCount = 0;
            var i = 0;
            Progress.Reset();
            foreach (var asset in toExportAssets)
            {
                Studio.StatusStripUpdate($"[{i}/{toExportCount}] Analyzing {asset.TypeString}: {asset.Text}");
                try
                {
                    if (ExportVizFile(asset, savePath, csvFile))
                    {
                        exportedCount++;
                    }
                }
                catch (Exception e)
                {
                    Logger.Error($"Analyze {asset.Type}:{asset.Text} error", e);
                }

                Progress.Report(++i, toExportCount);
            }

            var statusText = exportedCount == 0 ? "Nothing analyzed." : $"Finished analyzing {exportedCount} assets.";
            if (toExportCount > exportedCount)
            {
                statusText += $" {toExportCount - exportedCount} assets skipped";
            }

            Studio.StatusStripUpdate(statusText);
        }

        public static bool ExportVizFile(AssetItem item, string savePath, StreamWriter csvFile)
        {
            var result = true;
            var filename = string.Empty;
            var hash = string.Empty;
            var dimension = string.Empty;
            var format = string.Empty;
            var wrapMode = string.Empty;
            byte[] rawData = null;

            var sourcePath = savePath.Replace("-pkg", Path.DirectorySeparatorChar.ToString());
            var exportPath = Path.Combine(savePath, item.TypeString);

            switch (item.Type)
            {
                case ClassIDType.Texture2D:
                {
                    var texture2D = (Texture2D)item.Asset;
                    dimension = texture2D.m_MipMap
                        ? $"{texture2D.m_Width}x{texture2D.m_Height} mips:{texture2D.m_MipCount}"
                        : $"{texture2D.m_Width}x{texture2D.m_Height}";

                    if (texture2D.m_Width >= 512 || texture2D.m_Height >= 512)
                    {
                        result = Exporter.ExportTexture2D(item, exportPath, out var exportFullPath);
                        if (result)
                        {
                            filename = RelativeName(exportFullPath, exportPath, item.TypeString);
                            rawData = File.ReadAllBytes(exportFullPath);
                        }
                    }
                    else
                    {
                        rawData = texture2D.image_data.GetData();
                    }

                    format = texture2D.m_TextureFormat.ToString();
                    var mode = texture2D.m_TextureSettings.m_WrapMode;
                    wrapMode = mode >= 0 && mode < WrapModes.Length ? WrapModes[mode] : mode.ToString();
                    break;
                }
                case ClassIDType.Mesh:
                {
                    var mesh = (Mesh)item.Asset;
                    if (mesh.m_VertexCount > 1000)
                    {
                        result = Exporter.ExportMesh(item, exportPath, out var exportFullPath);
                        if (result)
                        {
                            filename = RelativeName(exportFullPath, exportPath, item.TypeString);
                            rawData = File.ReadAllBytes(exportFullPath);
                        }
                    }
                    else
                    {
                        rawData = item.Asset.GetRawData();
                    }

                    dimension = $"vtx:{mesh.m_VertexCount} idx:{mesh.m_Indices.Count} uv:{mesh.m_UV0?.Length} n:{mesh.m_Normals?.Length}";
                    break;
                }
                case ClassIDType.Font:
                {
                    var font = (Font)item.Asset;
                    rawData = font.m_FontData;
                    break;
                }
                case ClassIDType.TextAsset:
                case ClassIDType.Texture2DArray:
                case ClassIDType.Shader:
                case ClassIDType.AudioClip:
                case ClassIDType.AnimationClip:
                {
                    rawData = item.Asset.GetRawData();
                    break;
                }
                default:
                    return false;
            }

            if (rawData != null)
            {
                using (var md5 = MD5.Create())
                {
                    var retVal = md5.ComputeHash(rawData);
                    var sb = new StringBuilder();
                    foreach (var b in retVal)
                    {
                        sb.Append(b.ToString("x2"));
                    }
                    hash = sb.ToString();
                }
            }

            item.Text = item.Text.Replace("\0", "");
            var originalFile = item.SourceFile.originalPath ?? item.SourceFile.fullName;
            originalFile = originalFile.Replace(sourcePath, string.Empty).Replace("\\", "/");

            csvFile.Write(string.Format("{0}\t{1}\t{2}\t{3}\t{4}\t{5}\t{6}\t{7}\t{8}\t{9}\n",
                item.Text, item.Container, item.TypeString, dimension, format, item.FullSize,
                filename, hash, originalFile, wrapMode));

            return result;
        }

        private static string RelativeName(string fullPath, string exportPath, string typeName)
        {
            return (typeName + "/" + Path.GetFileName(fullPath)).Replace("\\", "/");
        }
    }
}

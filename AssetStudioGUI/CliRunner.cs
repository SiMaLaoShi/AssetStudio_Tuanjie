using AssetStudio;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

namespace AssetStudioGUI
{
    internal static class CliRunner
    {
        private const int ATTACH_PARENT_PROCESS = -1;
        private const int ConsoleInfoVerbosity = 1;
        private const int ConsoleDebugVerbosity = 2;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(int dwProcessId);

        public static int Run(string[] args)
        {
            AttachConsole(ATTACH_PARENT_PROCESS);

            var options = new CliOptions();
            try
            {
                if (!Parse(args, options))
                {
                    PrintUsage();
                    return 1;
                }
            }
            catch (Exception e)
            {
                Console.Error.WriteLine(e.Message);
                PrintUsage();
                return 1;
            }

            var loggers = new ConsoleLoggers();
            Logger.Default = new CliLogger(options.Verbosity, loggers);

            try
            {
                return Execute(options);
            }
            catch (Exception e)
            {
                Logger.Error($"CLI failed: {e.Message}", e);
                return 1;
            }
        }

        private static int Execute(CliOptions options)
        {
            Directory.CreateDirectory(options.OutputPath);

            Studio.InteractiveDialogs = false;
            Studio.StatusStripUpdate = s => Console.WriteLine(s);
            Studio.ErrorHandler = m => Logger.Default.Log(LoggerEvent.Error, m);
            Progress.Default = new NullProgress();

            if (!string.IsNullOrEmpty(options.AssemblyPath))
            {
                Studio.assemblyLoader.Load(options.AssemblyPath);
            }

            ApplySettings(options);

            Studio.assetsManager.SpecifyUnityVersion = options.UnityVersion;

            var isFolder = options.InputPaths.Count == 1 && Directory.Exists(options.InputPaths[0]);
            if (isFolder)
            {
                Studio.assetsManager.LoadFolder(options.InputPaths[0]);
            }
            else
            {
                Studio.assetsManager.LoadFiles(options.InputPaths.ToArray());
            }

            Studio.BuildAssetData();

            var toExport = Studio.exportableAssets;
            if (toExport.Count == 0)
            {
                Logger.Error("Nothing to export.");
                return 1;
            }

            if (options.Analyze)
            {
                Logger.Info($"Analyzing {toExport.Count} assets...");
                var tsvPath = Path.Combine(options.OutputPath, "pkg.tsv");
                using (var writer = new StreamWriter(tsvPath, false, new UTF8Encoding(false)))
                {
                    Analyzer.ExportPackage(options.OutputPath, toExport, writer);
                }
                Logger.Info($"Done. Wrote {tsvPath}.");
                RunPkgScript(options, tsvPath);
                return 0;
            }

            Logger.Info($"Exporting {toExport.Count} assets...");
            var exported = Studio.ExportAssetsSync(options.OutputPath, toExport, ExportType.Convert);
            Logger.Info($"Done. Exported {exported}/{toExport.Count} assets into {options.OutputPath}.");
            return 0;
        }

        private static void RunPkgScript(CliOptions options, string tsvPath)
        {
            var baseDir = AppDomain.CurrentDomain.BaseDirectory;
            var scriptExe = Path.Combine(baseDir, "script.exe");
            var pkgPy = Path.Combine(baseDir, "pkg.py");

            string fileName;
            string arguments;
            if (!options.NoScript && File.Exists(scriptExe))
            {
                fileName = scriptExe;
                arguments = $"\"{tsvPath}\"";
            }
            else if (!options.NoScript && File.Exists(pkgPy))
            {
                fileName = "python.exe";
                arguments = $"\"{pkgPy}\" \"{tsvPath}\"";
            }
            else
            {
                return;
            }

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = fileName,
                    Arguments = arguments,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                using (var process = Process.Start(psi))
                {
                    Console.Write(process.StandardOutput.ReadToEnd());
                    Console.Error.Write(process.StandardError.ReadToEnd());
                    process.WaitForExit();
                }
            }
            catch (Exception e)
            {
                Logger.Error($"Failed to run report script: {e.Message}", e);
            }
        }

        private static void ApplySettings(CliOptions options)
        {
            var settings = Properties.Settings.Default;
            settings.convertTexture = !options.NoConvertTexture;
            settings.convertAudio = !options.NoConvertAudio;
            settings.convertType = options.ConvertType;

            settings.assetGroupOption = options.GroupOption;
            settings.openAfterExport = false;
            settings.displayAll = false;
            settings.restoreExtensionName = false;
            settings.decompileLua = false;
        }

        private static bool Parse(string[] args, CliOptions options)
        {
            for (var i = 0; i < args.Length; i++)
            {
                var arg = args[i];
                if (string.Equals(arg, "--cli", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                switch (arg.ToLowerInvariant())
                {
                    case "-i":
                    case "--input":
                        options.InputPaths.Add(NextValue(args, ref i, arg));
                        break;
                    case "-o":
                    case "--output":
                        options.OutputPath = NextValue(args, ref i, arg);
                        break;
                    case "--unity-version":
                        options.UnityVersion = NextValue(args, ref i, arg);
                        break;
                    case "--assembly":
                        options.AssemblyPath = NextValue(args, ref i, arg);
                        break;
                    case "--convert-type":
                        options.ConvertType = ParseConvertType(NextValue(args, ref i, arg));
                        break;
                    case "--no-convert-texture":
                        options.NoConvertTexture = true;
                        break;
                    case "--no-convert-audio":
                        options.NoConvertAudio = true;
                        break;
                    case "--group":
                        options.GroupOption = ParseGroupOption(NextValue(args, ref i, arg));
                        break;
                    case "--analyze":
                        options.Analyze = true;
                        break;
                    case "--no-script":
                        options.NoScript = true;
                        break;
                    case "-v":
                    case "--verbose":
                        options.Verbosity = ConsoleDebugVerbosity;
                        break;
                    default:
                        if (!arg.StartsWith("-", StringComparison.Ordinal))
                        {
                            options.InputPaths.Add(arg);
                            break;
                        }
                        Console.Error.WriteLine($"Unknown argument: {arg}");
                        return false;
                }
            }

            if (options.InputPaths.Count == 0)
            {
                Console.Error.WriteLine("An input file or folder is required (--input).");
                return false;
            }

            foreach (var path in options.InputPaths)
            {
                if (!File.Exists(path) && !Directory.Exists(path))
                {
                    Console.Error.WriteLine($"Input path does not exist: {path}");
                    return false;
                }
            }

            if (string.IsNullOrEmpty(options.OutputPath))
            {
                options.OutputPath = DefaultOutputPath(options.InputPaths[0]);
            }

            return true;
        }

        private static string DefaultOutputPath(string inputPath)
        {
            var fullPath = Path.GetFullPath(inputPath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var parent = Path.GetDirectoryName(fullPath);

            if (Directory.Exists(fullPath))
            {
                return Path.Combine(parent, Path.GetFileName(fullPath) + ".pkg-doctor");
            }

            return Path.Combine(parent, Path.GetFileNameWithoutExtension(fullPath) + ".pkg-doctor");
        }

        private static string NextValue(string[] args, ref int index, string arg)
        {
            if (index + 1 >= args.Length)
            {
                throw new ArgumentException($"Missing value for {arg}");
            }

            return args[++index];
        }

        private static ImageFormat ParseConvertType(string value)
        {
            if (value.StartsWith(".", StringComparison.Ordinal))
            {
                value = value.Substring(1);
            }

            if (string.Equals(value, "jpg", StringComparison.OrdinalIgnoreCase))
            {
                return ImageFormat.Jpeg;
            }

            if (Enum.TryParse<ImageFormat>(value, true, out var format))
            {
                return format;
            }

            throw new ArgumentException($"Unsupported convert type: {value} (expected png, jpg, bmp or tga)");
        }

        private static int ParseGroupOption(string value)
        {
            if (int.TryParse(value, out var option) && option >= 0 && option <= 2)
            {
                return option;
            }

            throw new ArgumentException($"Unsupported group option: {value} (expected 0, 1 or 2)");
        }

        private static void PrintUsage()
        {
            Console.Error.WriteLine(@"AssetStudio_Tuanjie CLI

Usage:
  AssetStudioGUI.exe --cli [options] <file-or-folder> [<file-or-folder>...]
  AssetStudioGUI.exe --cli --analyze /path/to/game.apk

Options:
  -i, --input <path>        Input asset/bundle file or folder. Repeatable.
                            May also be given as a bare positional argument.
  -o, --output <folder>     Output folder. Defaults to <input>.pkg-doctor next to the input.
      --unity-version <v>   Override the Unity version, e.g. 2022.3.27f1.
      --assembly <folder>   Assembly folder for MonoBehaviour parsing.
      --convert-type <fmt>  Texture format: png (default), jpg, bmp, tga.
      --no-convert-texture  Keep raw texture data instead of converting.
      --no-convert-audio    Keep raw audio data instead of converting to wav.
      --group <0|1|2>       Output layout: 0 type (default), 1 container, 2 source file.
      --analyze             Package analysis mode: write pkg.tsv and run pkg.py/script.exe.
      --no-script           With --analyze, skip running the report script.
  -v, --verbose             Print verbose parse logs.");
        }

        private sealed class CliOptions
        {
            public readonly List<string> InputPaths = new List<string>();
            public string OutputPath;
            public string UnityVersion;
            public string AssemblyPath;
            public ImageFormat ConvertType = ImageFormat.Png;
            public bool NoConvertTexture;
            public bool NoConvertAudio;
            public int GroupOption;
            public bool Analyze;
            public bool NoScript;
            public int Verbosity = ConsoleInfoVerbosity;
        }

        private sealed class ConsoleLoggers
        {
            public readonly HashSet<string> Seen = new HashSet<string>(StringComparer.Ordinal);
        }

        private sealed class CliLogger : ILogger
        {
            private readonly int verbosity;
            private readonly ConsoleLoggers state;

            public CliLogger(int verbosity, ConsoleLoggers state)
            {
                this.verbosity = verbosity;
                this.state = state;
            }

            public void Log(LoggerEvent loggerEvent, string message)
            {
                if (loggerEvent == LoggerEvent.Error)
                {
                    Console.Error.WriteLine(message);
                    return;
                }

                var isInfo = loggerEvent == LoggerEvent.Info;
                if (isInfo && verbosity < ConsoleInfoVerbosity)
                {
                    return;
                }

                if (!isInfo && verbosity < ConsoleDebugVerbosity)
                {
                    return;
                }

                if (!state.Seen.Add(loggerEvent + message))
                {
                    return;
                }

                Console.WriteLine(message);
            }
        }

        private sealed class NullProgress : IProgress<int>
        {
            public void Report(int value) { }
        }
    }
}

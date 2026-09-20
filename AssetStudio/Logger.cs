using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace AssetStudio
{
    public static class Logger
    {
        public static ILogger Default = new DummyLogger();

        public static string UnityVersion;

        private static readonly object SyncRoot = new object();
        private static readonly string LogFilePath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "AssetStudio.log");
        private static int logId;

        public static void Verbose(string message) => Log(LoggerEvent.Verbose, message);
        public static void Debug(string message) => Log(LoggerEvent.Debug, message);
        public static void Info(string message) => Log(LoggerEvent.Info, message);
        public static void Warning(string message) => Log(LoggerEvent.Warning, message);
        public static void Error(string message) => Log(LoggerEvent.Error, message);

        public static void Error(string message, Exception e)
        {
            var sb = new StringBuilder();
            sb.AppendLine(message);
            sb.AppendLine(e.ToString());
            Log(LoggerEvent.Error, sb.ToString());
        }

        private static void Log(LoggerEvent loggerEvent, string message)
        {
            var id = Interlocked.Increment(ref logId);
            var text = Format(id, loggerEvent, message);

            Default.Log(loggerEvent, text);

            if (loggerEvent == LoggerEvent.Error)
            {
                WriteToFile(text);
            }
        }

        private static string Format(int id, LoggerEvent loggerEvent, string message)
        {
            var sb = new StringBuilder();
            sb.Append('[').Append(EventCode(loggerEvent)).Append(id).Append(']');

            if (!string.IsNullOrEmpty(UnityVersion))
            {
                sb.Append("[Unity ").Append(UnityVersion).Append(']');
            }

            sb.Append(message);
            sb.Append(Environment.NewLine)
                .Append("    at ")
                .Append(CallSite());
            return sb.ToString();
        }

        private static string EventCode(LoggerEvent loggerEvent)
        {
            switch (loggerEvent)
            {
                case LoggerEvent.Verbose: return "V";
                case LoggerEvent.Debug: return "D";
                case LoggerEvent.Info: return "I";
                case LoggerEvent.Warning: return "W";
                default: return "E";
            }
        }

        private static string CallSite()
        {
            var trace = new StackTrace(2, false);
            var sb = new StringBuilder();
            var frames = trace.GetFrames();
            if (frames == null)
            {
                return "?";
            }

            var count = 0;
            foreach (var frame in frames)
            {
                var method = frame.GetMethod();
                if (method == null || method.DeclaringType == typeof(Logger))
                {
                    continue;
                }

                if (count > 0)
                {
                    sb.Append(" <- ");
                }

                sb.Append(method.DeclaringType?.FullName).Append('.').Append(method.Name);

                if (++count == 4)
                {
                    break;
                }
            }

            return sb.Length == 0 ? "?" : sb.ToString();
        }

        private static void WriteToFile(string text)
        {
            try
            {
                lock (SyncRoot)
                {
                    File.AppendAllText(LogFilePath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {text}{Environment.NewLine}");
                }
            }
            catch
            {
                // file logging must never break the caller
            }
        }
    }
}
